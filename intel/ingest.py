"""Ingestion adapters — read existing CSVs + gmap SQLite, write to unified DB.

Sources handled:
  • tow_reviews.csv          → Review
  • tow_competitors.csv      → Competitor
  • tow_news.csv             → NewsItem
  • tow_pricing.csv          → PriceRecord
  • tow_intel.csv            → IntelSignal
  • <gmap dir>/reviews.db    → Review (richer fields)
  • <gmap dir>/*_reviews.csv → Review (fallback if no db)

Idempotent: content_hash enforces uniqueness, so re-runs are safe.
"""
from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from .analysis import enrich_news, enrich_review, sentiment_label
from .db import (
    AppReview, Competitor, IntelSignal, NewsItem, PriceRecord, Product, Review,
    session_scope,
)
from .dedup_simhash import content_hash, simhash
from .events import Event, bus

ROOT = Path(__file__).resolve().parent.parent
PARENT_ROOT = ROOT.parent  # /Users/.../Desktop/startup
GMAP_DB_CANDIDATES = [
    ROOT / "reviews.db",
    PARENT_ROOT / "gmap agent" / "reviews.db",
]
GMAP_CSV_CANDIDATES = [
    ROOT / "gmap agent" / "organic_world_all_reviews.csv",      # storm/gmap agent/
    PARENT_ROOT / "gmap agent" / "organic_world_all_reviews.csv",  # sibling dir
    ROOT / "organic_world_all_reviews.csv",                     # root fallback
]


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def _float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        if value in (None, "", "None"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default: Optional[int] = None) -> Optional[int]:
    try:
        if value in (None, "", "None"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ── Reviews from tow_reviews.csv ──────────────────────────────────────

def ingest_reviews_csv(path: Optional[Path] = None) -> int:
    path = path or (ROOT / "tow_reviews.csv")
    rows = _read_csv(path)
    added = 0
    with session_scope() as session:
        for r in rows:
            text = (r.get("review_text") or "").strip()
            if not text:
                continue
            store = (r.get("store_location") or "").strip()
            ch = content_hash("review", store, text)
            if session.scalar(select(Review.id).where(Review.content_hash == ch)):
                continue
            rating = _float(r.get("rating"))
            score, label = enrich_review(text, rating)
            review = Review(
                store_location=store or "Unknown",
                product_name=r.get("product_name") or None,
                reviewer_name=r.get("reviewer_name") or None,
                rating=rating,
                review_text=text,
                source=r.get("source") or "csv",
                sentiment=label,
                sentiment_score=score,
                content_hash=ch,
                simhash=simhash(text),
                scraped_at=_parse_dt(r.get("timestamp", "")),
            )
            session.add(review)
            session.flush()
            bus.publish_sync(Event(type="review.created", payload={
                "id": review.id, "store": store, "rating": rating, "sentiment": label,
            }))
            added += 1
    return added


# ── Reviews from gmap agent (SQLite preferred, CSV fallback) ──────────

def _find_gmap_db() -> Optional[Path]:
    for c in GMAP_DB_CANDIDATES:
        if c.exists():
            return c
    return None


def ingest_gmap_reviews() -> int:
    db = _find_gmap_db()
    if db:
        return _ingest_gmap_sqlite(db)
    for c in GMAP_CSV_CANDIDATES:
        if c.exists():
            return _ingest_gmap_csv(c)
    return 0


def _ingest_gmap_sqlite(db_path: Path) -> int:
    added = 0
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        tables = [
            row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        # Find a reviews-like table
        review_table = next(
            (t for t in tables if "review" in t.lower()),
            None,
        )
        if not review_table:
            return 0
        cur = con.execute(f"SELECT * FROM {review_table}")
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        con.close()

    seen: set[str] = set()
    with session_scope() as session:
        for r in rows:
            text = (r.get("review_text") or r.get("text") or "").strip()
            if not text:
                continue
            store = (r.get("store_name") or r.get("store") or "The Organic World").strip()
            ch = content_hash("review", store, text, r.get("reviewer_name") or "")
            if ch in seen:
                continue
            if session.scalar(select(Review.id).where(Review.content_hash == ch)):
                continue
            seen.add(ch)
            rating = _float(r.get("rating"))
            score, label = enrich_review(text, rating)
            review = Review(
                store_location=store,
                store_city=r.get("store_city"),
                store_address=r.get("store_address"),
                store_url=r.get("store_url"),
                reviewer_name=r.get("reviewer_name"),
                rating=rating,
                review_text=text,
                review_date=r.get("review_date"),
                helpful_votes=_int(r.get("helpful_votes")),
                owner_response=r.get("owner_response"),
                source="Google Maps",
                sentiment=label,
                sentiment_score=score,
                content_hash=ch,
                simhash=simhash(text),
                scraped_at=_parse_dt(r.get("scraped_at") or ""),
            )
            session.add(review)
            added += 1
    return added


def _ingest_gmap_csv(path: Path) -> int:
    rows = _read_csv(path)
    added = 0
    seen: set[str] = set()
    with session_scope() as session:
        for r in rows:
            text = (r.get("review_text") or "").strip()
            if not text:
                continue
            store = (r.get("store_name") or r.get("store_location") or "The Organic World").strip()
            ch = content_hash(
                "review", store, text, r.get("reviewer_name") or "",
            )
            if ch in seen:
                continue
            if session.scalar(select(Review.id).where(Review.content_hash == ch)):
                continue
            seen.add(ch)
            rating = _float(r.get("rating"))
            score, label = enrich_review(text, rating)
            session.add(Review(
                store_location=store,
                store_city=r.get("store_city"),
                store_address=r.get("store_address"),
                store_url=r.get("store_url"),
                reviewer_name=r.get("reviewer_name"),
                rating=rating,
                review_text=text,
                review_date=r.get("review_date"),
                helpful_votes=_int(r.get("helpful_votes")),
                owner_response=r.get("owner_response"),
                source="Google Maps",
                sentiment=label,
                sentiment_score=score,
                content_hash=ch,
                simhash=simhash(text),
                scraped_at=_parse_dt(r.get("scraped_at") or ""),
            ))
            added += 1
    return added


# ── Competitors / News / Pricing / Intel from existing CSVs ───────────

def ingest_competitors_csv(path: Optional[Path] = None) -> int:
    path = path or (ROOT / "tow_competitors.csv")
    rows = _read_csv(path)
    added = 0
    seen: set[str] = set()
    with session_scope() as session:
        for r in rows:
            name = (r.get("competitor_name") or "").strip()
            if not name:
                continue
            ch = content_hash("competitor", name, r.get("location") or "")
            if ch in seen:
                continue
            if session.scalar(select(Competitor.id).where(Competitor.content_hash == ch)):
                continue
            seen.add(ch)
            session.add(Competitor(
                competitor_name=name,
                location=r.get("location"),
                category=r.get("category"),
                strengths=r.get("strengths"),
                weaknesses=r.get("weaknesses"),
                price_positioning=r.get("price_positioning"),
                notable_products=r.get("notable_products"),
                online_presence=r.get("online_presence"),
                source=r.get("source") or "csv",
                content_hash=ch,
            ))
            added += 1
    return added


def ingest_news_csv(path: Optional[Path] = None) -> int:
    path = path or (ROOT / "tow_news.csv")
    rows = _read_csv(path)
    added = 0
    seen: set[str] = set()
    with session_scope() as session:
        for r in rows:
            headline = (r.get("headline") or "").strip()
            summary = (r.get("summary") or "").strip()
            if not headline and not summary:
                continue
            ch = content_hash("news", headline, summary[:200])
            if ch in seen:
                continue
            if session.scalar(select(NewsItem.id).where(NewsItem.content_hash == ch)):
                continue
            seen.add(ch)
            score, label = enrich_news(f"{headline}. {summary}")
            item = NewsItem(
                headline=headline or summary[:120],
                summary=summary,
                url=r.get("url"),
                source=r.get("source") or "unknown",
                relevance_tag=r.get("relevance_tag") or "market_trend",
                sentiment=label,
                sentiment_score=score,
                content_hash=ch,
                simhash=simhash(f"{headline} {summary}"),
            )
            session.add(item)
            session.flush()
            bus.publish_sync(Event(type="news.created", payload={
                "id": item.id, "headline": item.headline[:140], "tag": item.relevance_tag,
            }))
            added += 1
    return added


def ingest_pricing_csv(path: Optional[Path] = None) -> int:
    path = path or (ROOT / "tow_pricing.csv")
    rows = _read_csv(path)
    added = 0
    with session_scope() as session:
        for r in rows:
            product = (r.get("product_name") or "").strip()
            competitor = (r.get("competitor_name") or "").strip()
            if not product or not competitor:
                continue
            ch = content_hash("pricing", product, competitor, r.get("tow_price") or "")
            if session.scalar(select(PriceRecord.id).where(PriceRecord.content_hash == ch)):
                continue
            session.add(PriceRecord(
                product_name=product,
                tow_price=_float(r.get("tow_price"), 0.0) or 0.0,
                competitor_name=competitor,
                competitor_price=_float(r.get("competitor_price"), 0.0) or 0.0,
                price_diff_pct=_float(r.get("price_diff_pct"), 0.0) or 0.0,
                notes=r.get("notes"),
                source=r.get("source") or "csv",
                content_hash=ch,
            ))
            added += 1
    return added


def ingest_intel_csv(path: Optional[Path] = None) -> int:
    path = path or (ROOT / "tow_intel.csv")
    rows = _read_csv(path)
    added = 0
    seen: set[str] = set()
    with session_scope() as session:
        for r in rows:
            subject = (r.get("subject") or "").strip()
            detail = (r.get("detail") or "").strip()
            if not subject:
                continue
            ch = content_hash("intel", subject, detail[:200])
            if ch in seen:
                continue
            if session.scalar(select(IntelSignal.id).where(IntelSignal.content_hash == ch)):
                continue
            seen.add(ch)
            sig = IntelSignal(
                intel_type=r.get("intel_type") or "trend",
                subject=subject,
                detail=detail,
                strategic_implication=r.get("strategic_implication"),
                source=r.get("source") or "csv",
                content_hash=ch,
            )
            session.add(sig)
            session.flush()
            bus.publish_sync(Event(type="intel.created", payload={
                "id": sig.id, "type": sig.intel_type, "subject": subject[:140],
            }))
            added += 1
    return added


# ── App Store / Play Store reviews ───────────────────────────────────

DATA_DIR = ROOT / "Data"
APP_REVIEW_CANDIDATES = [
    DATA_DIR / "app_store_reviews.csv",
    DATA_DIR / "play_store_reviews.csv",
    ROOT / "app_store_reviews.csv",
    ROOT / "play_store_reviews.csv",
]


def ingest_app_reviews() -> int:
    """Ingest all app-review CSVs from Data/ directory."""
    added = 0
    seen: set[str] = set()
    csv_paths = [p for p in APP_REVIEW_CANDIDATES if p.exists()]
    if not csv_paths:
        return 0
    with session_scope() as session:
        for path in csv_paths:
            rows = _read_csv(path)
            for r in rows:
                text = (r.get("review_text") or "").strip()
                if not text:
                    continue
                source = (r.get("source") or "unknown").strip()
                reviewer = (r.get("reviewer") or "").strip()
                ch = content_hash("app_review", source, reviewer, text)
                if ch in seen:
                    continue
                if session.scalar(select(AppReview.id).where(AppReview.content_hash == ch)):
                    continue
                seen.add(ch)
                session.add(AppReview(
                    source=source,
                    reviewer=reviewer or None,
                    star_rating=_int(r.get("star_rating")),
                    review_text=text,
                    sentiment=r.get("sentiment") or None,
                    rating_implied=_float(r.get("rating_implied")),
                    topic=(r.get("topic") or "").strip() or None,
                    summary=(r.get("summary") or "").strip() or None,
                    review_date=(r.get("review_date") or "").strip() or None,
                    thumbs_up=_int(r.get("thumbs_up")),
                    content_hash=ch,
                    scraped_at=_parse_dt(r.get("scraped_at") or ""),
                ))
                added += 1
    return added


# ── Product catalogue ─────────────────────────────────────────────────

PRODUCT_CANDIDATES = [
    DATA_DIR / "tow_products.csv",
    ROOT / "tow_products.csv",
]


def ingest_products() -> int:
    """Ingest TOW product catalogue from tow_products.csv."""
    added = 0
    seen: set[str] = set()
    path = next((p for p in PRODUCT_CANDIDATES if p.exists()), None)
    if not path:
        return 0
    rows = _read_csv(path)
    with session_scope() as session:
        for r in rows:
            name = (r.get("product_name") or "").strip()
            if not name:
                continue
            pid = (r.get("product_id") or "").strip()
            ch = content_hash("product", pid, name)
            if ch in seen:
                continue
            if session.scalar(select(Product.id).where(Product.content_hash == ch)):
                continue
            seen.add(ch)
            session.add(Product(
                product_id=pid or None,
                product_name=name,
                brand=(r.get("brand") or "").strip() or None,
                category=(r.get("category") or "").strip() or None,
                category_id=(r.get("category_id") or "").strip() or None,
                min_price_inr=_float(r.get("min_price_inr")),
                max_price_inr=_float(r.get("max_price_inr")),
                discount_pct=_float(r.get("discount_pct")),
                discount_type=(r.get("discount_type") or "").strip() or None,
                unit=(r.get("unit") or "").strip() or None,
                stock_status=(r.get("stock_status") or "").strip() or None,
                avg_rating=_float(r.get("avg_rating")),
                review_count=_int(r.get("review_count")),
                variations_count=_int(r.get("variations_count")),
                slug=(r.get("slug") or "").strip() or None,
                content_hash=ch,
                scraped_at=_parse_dt(r.get("scraped_at") or ""),
            ))
            added += 1
    return added


# ── Top-level orchestrator ───────────────────────────────────────────

def ingest_all() -> dict[str, int]:
    return {
        "reviews_csv": ingest_reviews_csv(),
        "reviews_gmap": ingest_gmap_reviews(),
        "competitors": ingest_competitors_csv(),
        "news": ingest_news_csv(),
        "pricing": ingest_pricing_csv(),
        "intel": ingest_intel_csv(),
        "app_reviews": ingest_app_reviews(),
        "products": ingest_products(),
    }
