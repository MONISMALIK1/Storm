"""FastAPI service — REST endpoints, WebSocket push, dashboard static mount."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import (
    Depends, FastAPI, HTTPException, Query, Request, WebSocket,
    WebSocketDisconnect, status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import alerts as alerts_module
from . import ingest as ingest_module
from .analysis import keyword_counts, review_trend
from .auth import (
    authenticate, client_ip, create_access_token, create_user,
    get_current_user, log_audit, require_role,
)
from .db import (
    Alert, AppReview, Competitor, IntelSignal, NewsItem, PriceRecord, Product,
    Review, User, get_session, init_db, session_scope,
)
from .events import Event, bus
from .schemas import (
    AlertOut, AppReviewOut, AppSummary, CompetitorOut, DashboardSummary,
    IntelOut, NewsOut, PriceOut, ProductOut, ProductSummary,
    ReviewOut, TokenResponse, UserCreate, UserPublic,
)


DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    bus.bind_loop(asyncio.get_running_loop())
    yield


import os as _os

# In production set INTEL_ALLOWED_ORIGINS="https://yourdomain.com,https://www.yourdomain.com"
# Leave unset (or set to "*") for local dev only.
_raw_origins = _os.environ.get("INTEL_ALLOWED_ORIGINS", "*")
_ALLOWED_ORIGINS: list[str] = (
    ["*"] if _raw_origins.strip() == "*"
    else [o.strip() for o in _raw_origins.split(",") if o.strip()]
)

# Disable interactive docs in production
_ENV = _os.environ.get("INTEL_ENV", "development")
app = FastAPI(
    title="TOW Competitive Intelligence API",
    version="0.1.0",
    lifespan=_lifespan,
    docs_url=None if _ENV == "production" else "/docs",
    redoc_url=None if _ENV == "production" else "/redoc",
    openapi_url=None if _ENV == "production" else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth ─────────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=TokenResponse)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    user = authenticate(session, form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )
    log_audit(session, user.id, "login", ip=client_ip(request))
    session.commit()
    token = create_access_token(user)
    return TokenResponse(access_token=token, role=user.role, email=user.email)


@app.get("/auth/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)):
    return user


@app.post("/admin/users", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def admin_create_user(
    payload: UserCreate,
    request: Request,
    admin: User = Depends(require_role("admin")),
):
    try:
        user = create_user(payload.email, payload.password, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    with session_scope() as s:
        log_audit(s, admin.id, "create_user", "user", user.id, ip=client_ip(request))
    return user


@app.get("/admin/users", response_model=list[UserPublic])
def admin_list_users(
    _: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    return list(session.scalars(select(User).order_by(User.created_at.desc())))


# ─── Reads (analyst role minimum) ─────────────────────────────────────

@app.get("/reviews", response_model=list[ReviewOut])
def list_reviews(
    store: Optional[str] = None,
    sentiment: Optional[str] = None,
    min_rating: Optional[float] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    q = select(Review).order_by(Review.created_at.desc())
    if store:
        q = q.where(Review.store_location.ilike(f"%{store}%"))
    if sentiment:
        q = q.where(Review.sentiment == sentiment)
    if min_rating is not None:
        q = q.where(Review.rating >= min_rating)
    q = q.offset(offset).limit(limit)
    return list(session.scalars(q))


@app.get("/news", response_model=list[NewsOut])
def list_news(
    tag: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = select(NewsItem).where(NewsItem.created_at >= cutoff).order_by(NewsItem.created_at.desc())
    if tag:
        q = q.where(NewsItem.relevance_tag == tag)
    return list(session.scalars(q.limit(limit)))


@app.get("/competitors", response_model=list[CompetitorOut])
def list_competitors(
    category: Optional[str] = None,
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    q = select(Competitor).order_by(Competitor.competitor_name)
    if category:
        q = q.where(Competitor.category == category)
    return list(session.scalars(q))


@app.get("/pricing", response_model=list[PriceOut])
def list_pricing(
    product: Optional[str] = None,
    competitor: Optional[str] = None,
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    q = select(PriceRecord).order_by(PriceRecord.created_at.desc())
    if product:
        q = q.where(PriceRecord.product_name.ilike(f"%{product}%"))
    if competitor:
        q = q.where(PriceRecord.competitor_name.ilike(f"%{competitor}%"))
    return list(session.scalars(q.limit(500)))


@app.get("/intel", response_model=list[IntelOut])
def list_intel(
    intel_type: Optional[str] = None,
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    q = select(IntelSignal).order_by(IntelSignal.created_at.desc())
    if intel_type:
        q = q.where(IntelSignal.intel_type == intel_type)
    return list(session.scalars(q.limit(500)))


# ─── Alerts ───────────────────────────────────────────────────────────

@app.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    only_unack: bool = True,
    hours: int = Query(48, ge=1, le=720),
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    q = select(Alert).where(Alert.created_at >= cutoff).order_by(Alert.created_at.desc())
    if only_unack:
        q = q.where(Alert.acknowledged.is_(False))
    return list(session.scalars(q.limit(500)))


@app.post("/alerts/{alert_id}/ack")
def ack_alert(
    alert_id: int,
    request: Request,
    user: User = Depends(require_role("analyst")),
):
    ok = alerts_module.acknowledge(alert_id, user.id)
    if not ok:
        raise HTTPException(404, "alert not found or already acknowledged")
    with session_scope() as s:
        log_audit(s, user.id, "ack_alert", "alert", alert_id, ip=client_ip(request))
    return {"ok": True}


@app.post("/alerts/scan")
def trigger_scan(_: User = Depends(require_role("analyst"))):
    new = alerts_module.run_detection()
    return {"new_alerts": len(new), "items": new}


# ─── Ingest trigger (admin) ───────────────────────────────────────────

@app.post("/admin/ingest")
def admin_ingest(_: User = Depends(require_role("admin"))):
    return ingest_module.ingest_all()


# ─── Dashboard summary ────────────────────────────────────────────────

@app.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    trend = review_trend(session, days=30)
    cutoff24 = datetime.utcnow() - timedelta(hours=24)
    news_24h = session.scalar(
        select(func.count()).select_from(NewsItem).where(NewsItem.created_at >= cutoff24)
    ) or 0
    intel_24h = session.scalar(
        select(func.count()).select_from(IntelSignal).where(IntelSignal.created_at >= cutoff24)
    ) or 0
    competitors = session.scalar(select(func.count()).select_from(Competitor)) or 0
    pricing = session.scalar(select(func.count()).select_from(PriceRecord)) or 0
    unack = session.scalar(
        select(func.count()).select_from(Alert).where(Alert.acknowledged.is_(False))
    ) or 0
    recent_texts = [
        r.review_text for r in session.scalars(
            select(Review).order_by(Review.created_at.desc()).limit(500)
        )
    ]
    return DashboardSummary(
        review_count=trend.get("count", 0),
        avg_rating=trend.get("avg_rating"),
        sentiment_split=trend.get("sentiment_split", {}),
        news_24h=int(news_24h),
        intel_24h=int(intel_24h),
        competitor_count=int(competitors),
        pricing_records=int(pricing),
        unacknowledged_alerts=int(unack),
        top_keywords=keyword_counts(recent_texts, top_n=15),
    )


# ─── App Reviews ─────────────────────────────────────────────────────

@app.get("/app-reviews", response_model=list[AppReviewOut])
def list_app_reviews(
    source: Optional[str] = None,
    sentiment: Optional[str] = None,
    topic: Optional[str] = None,
    min_stars: Optional[int] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    q = select(AppReview).order_by(AppReview.created_at.desc())
    if source:
        q = q.where(AppReview.source == source)
    if sentiment:
        q = q.where(AppReview.sentiment == sentiment)
    if topic:
        q = q.where(AppReview.topic.ilike(f"%{topic}%"))
    if min_stars is not None:
        q = q.where(AppReview.star_rating >= min_stars)
    return list(session.scalars(q.offset(offset).limit(limit)))


# ─── Products ─────────────────────────────────────────────────────────

@app.get("/products", response_model=list[ProductOut])
def list_products(
    category: Optional[str] = None,
    brand: Optional[str] = None,
    stock_status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    q = select(Product).order_by(Product.product_name)
    if category:
        q = q.where(Product.category.ilike(f"%{category}%"))
    if brand:
        q = q.where(Product.brand.ilike(f"%{brand}%"))
    if stock_status:
        q = q.where(Product.stock_status == stock_status)
    if search:
        q = q.where(Product.product_name.ilike(f"%{search}%"))
    return list(session.scalars(q.offset(offset).limit(limit)))


# ─── App summary ─────────────────────────────────────────────────────

_SAFETY_KEYWORDS = ["worms", "rotten", "stale", "expired", "mold", "spoilt", "spoiled", "bad smell", "maggots"]


@app.get("/dashboard/app-summary", response_model=AppSummary)
def app_summary(
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    rows = list(session.scalars(select(AppReview)))
    total = len(rows)
    if total == 0:
        return AppSummary(
            total_app_reviews=0, avg_star_rating=None,
            sentiment_split={}, topic_split={}, platform_split={},
            safety_complaint_count=0, nps_proxy=None,
        )

    ratings = [r.star_rating for r in rows if r.star_rating is not None]
    avg_stars = round(sum(ratings) / len(ratings), 2) if ratings else None

    sent_split: dict = {}
    for r in rows:
        k = r.sentiment or "unknown"
        sent_split[k] = sent_split.get(k, 0) + 1

    topic_split: dict = {}
    for r in rows:
        for t in (r.topic or "other").split(","):
            k = t.strip() or "other"
            topic_split[k] = topic_split.get(k, 0) + 1

    platform_split: dict = {}
    for r in rows:
        k = r.source or "unknown"
        platform_split[k] = platform_split.get(k, 0) + 1

    safety_count = sum(
        1 for r in rows
        if any(kw in (r.review_text or "").lower() for kw in _SAFETY_KEYWORDS)
    )

    recommend = sum(1 for r in rows if "recommend" in (r.review_text or "").lower())
    uninstall = sum(1 for r in rows if any(
        w in (r.review_text or "").lower() for w in ["uninstall", "terrible", "horrible"]
    ))
    nps = round((recommend - uninstall) / total * 100, 1) if total else None

    return AppSummary(
        total_app_reviews=total,
        avg_star_rating=avg_stars,
        sentiment_split=sent_split,
        topic_split=topic_split,
        platform_split=platform_split,
        safety_complaint_count=safety_count,
        nps_proxy=nps,
    )


# ─── Product summary ─────────────────────────────────────────────────

@app.get("/dashboard/product-summary", response_model=ProductSummary)
def product_summary(
    _: User = Depends(require_role("viewer")),
    session: Session = Depends(get_session),
):
    rows = list(session.scalars(select(Product)))
    total = len(rows)
    in_stock = sum(1 for p in rows if (p.stock_status or "").lower() not in ("", "none", "out_of_stock"))
    out_of_stock = total - in_stock

    # Category breakdown
    cat_map: dict = {}
    for p in rows:
        c = p.category or "Unknown"
        if c not in cat_map:
            cat_map[c] = {"category": c, "count": 0, "prices": []}
        cat_map[c]["count"] += 1
        if p.min_price_inr is not None:
            cat_map[c]["prices"].append(p.min_price_inr)
    categories = [
        {"category": v["category"], "count": v["count"],
         "avg_price": round(sum(v["prices"]) / len(v["prices"]), 2) if v["prices"] else None}
        for v in sorted(cat_map.values(), key=lambda x: x["count"], reverse=True)[:10]
    ]

    discounts = [p.discount_pct for p in rows if p.discount_pct is not None]
    avg_disc = round(sum(discounts) / len(discounts), 1) if discounts else None

    top_disc = sorted(
        [p for p in rows if p.discount_pct],
        key=lambda p: p.discount_pct or 0, reverse=True
    )[:5]
    top_discounted = [
        {"name": p.product_name, "discount_pct": p.discount_pct,
         "price": p.min_price_inr, "category": p.category}
        for p in top_disc
    ]

    return ProductSummary(
        total_products=total,
        in_stock=in_stock,
        out_of_stock=out_of_stock,
        categories=categories,
        avg_discount_pct=avg_disc,
        top_discounted=top_discounted,
    )


# ─── WebSocket: realtime event stream ────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: Optional[str] = None):
    """Connect as: ws://host/ws?token=<JWT>"""
    if not token:
        await ws.close(code=4401)
        return
    try:
        from .auth import decode_token
        payload = decode_token(token)
        int(payload["sub"])
    except Exception:
        await ws.close(code=4401)
        return

    await ws.accept()
    q = await bus.subscribe()
    try:
        await ws.send_text(Event(type="hello", payload={"ok": True}).to_json())
        while True:
            evt = await q.get()
            await ws.send_text(evt.to_json())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)


# ─── Static dashboard ─────────────────────────────────────────────────

if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")

    @app.get("/")
    def root():
        index = DASHBOARD_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"name": "TOW Intelligence API", "version": "0.1.0"})
else:
    @app.get("/")
    def root():
        return {"name": "TOW Intelligence API", "version": "0.1.0"}


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}
