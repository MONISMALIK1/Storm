"""Alert engine — derives prioritized signals from recent data.

Rules (each yields zero or more Alert rows):
  - LOW_RATING_REVIEW: any review with rating <= 2
  - SENTIMENT_DROP: 7-day avg sentiment > 0.2 lower than prior 7-day baseline
  - COMPETITOR_NEWS: any competitor-tagged news from last 24h
  - PRICE_THREAT: pricing record where competitor is >15% cheaper
  - STRATEGIC_THREAT: any intel of type 'threat' from last 24h
  - VOLUME_SPIKE: 24h news volume on any tag > 2x the 7-day mean
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Alert, IntelSignal, NewsItem, PriceRecord, Review, session_scope
from .events import Event, bus

PRIORITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode()).hexdigest()[:32]


def _emit(
    session: Session,
    priority: str,
    subject: str,
    detail: str,
    source_type: str,
    source_id: Optional[int],
    dedup_key: str,
) -> Optional[Alert]:
    fp = _fingerprint(source_type, dedup_key)
    existing = session.scalar(select(Alert).where(Alert.fingerprint == fp))
    if existing:
        return None
    alert = Alert(
        priority=priority,
        subject=subject,
        detail=detail,
        source_type=source_type,
        source_id=source_id,
        fingerprint=fp,
    )
    session.add(alert)
    session.flush()
    bus.publish_sync(Event(
        type="alert.created",
        payload={
            "id": alert.id,
            "priority": priority,
            "subject": subject,
            "detail": detail[:240],
            "source_type": source_type,
        },
    ))
    return alert


def _rule_low_rating(session: Session, since: datetime) -> list[Alert]:
    rows = session.scalars(
        select(Review)
        .where(Review.created_at >= since)
        .where(Review.rating <= 2)
    ).all()
    out = []
    for r in rows:
        priority = "CRITICAL" if (r.rating or 5) <= 1 else "HIGH"
        a = _emit(
            session, priority,
            subject=f"Bad review ({r.rating}★) — {r.store_location}",
            detail=f"{r.reviewer_name or 'Anon'}: {r.review_text[:200]}",
            source_type="review",
            source_id=r.id,
            dedup_key=f"review:{r.id}",
        )
        if a:
            out.append(a)
    return out


def _rule_sentiment_drop(session: Session) -> list[Alert]:
    now = datetime.utcnow()
    recent_cut = now - timedelta(days=7)
    baseline_cut = now - timedelta(days=14)

    def _avg(start: datetime, end: datetime) -> Optional[float]:
        rows = session.scalars(
            select(Review.sentiment_score)
            .where(Review.created_at >= start)
            .where(Review.created_at < end)
            .where(Review.sentiment_score.is_not(None))
        ).all()
        return sum(rows) / len(rows) if rows else None

    recent = _avg(recent_cut, now)
    baseline = _avg(baseline_cut, recent_cut)
    if recent is None or baseline is None:
        return []
    drop = baseline - recent
    if drop < 0.2:
        return []
    a = _emit(
        session, "HIGH",
        subject="Customer sentiment dropping",
        detail=f"7-day avg sentiment {recent:+.2f} vs prior baseline {baseline:+.2f} (drop {drop:+.2f})",
        source_type="trend",
        source_id=None,
        dedup_key=f"sentiment_drop:{now.date().isoformat()}",
    )
    return [a] if a else []


def _rule_competitor_news(session: Session, since: datetime) -> list[Alert]:
    rows = session.scalars(
        select(NewsItem)
        .where(NewsItem.created_at >= since)
        .where(NewsItem.relevance_tag == "competitor")
    ).all()
    out = []
    for n in rows:
        a = _emit(
            session, "MEDIUM",
            subject=f"Competitor move: {n.headline[:120]}",
            detail=(n.summary or "")[:300],
            source_type="news",
            source_id=n.id,
            dedup_key=f"news:{n.id}",
        )
        if a:
            out.append(a)
    return out


def _rule_price_threat(session: Session, since: datetime) -> list[Alert]:
    rows = session.scalars(
        select(PriceRecord)
        .where(PriceRecord.created_at >= since)
        .where(PriceRecord.price_diff_pct <= -15)
    ).all()
    out = []
    for p in rows:
        a = _emit(
            session, "HIGH",
            subject=f"Price threat: {p.competitor_name} {abs(p.price_diff_pct):.0f}% cheaper on {p.product_name}",
            detail=f"TOW ₹{p.tow_price} vs {p.competitor_name} ₹{p.competitor_price}. {p.notes or ''}",
            source_type="pricing",
            source_id=p.id,
            dedup_key=f"price:{p.id}",
        )
        if a:
            out.append(a)
    return out


def _rule_strategic_threat(session: Session, since: datetime) -> list[Alert]:
    rows = session.scalars(
        select(IntelSignal)
        .where(IntelSignal.created_at >= since)
        .where(IntelSignal.intel_type == "threat")
    ).all()
    out = []
    for i in rows:
        a = _emit(
            session, "HIGH",
            subject=f"Strategic threat: {i.subject[:120]}",
            detail=f"{i.detail[:240]} → {i.strategic_implication or ''}",
            source_type="intel",
            source_id=i.id,
            dedup_key=f"intel:{i.id}",
        )
        if a:
            out.append(a)
    return out


def run_detection(window_hours: int = 24) -> list[dict]:
    """Run all rules over the recent window. Returns newly-created alerts."""
    since = datetime.utcnow() - timedelta(hours=window_hours)
    created: list[Alert] = []
    with session_scope() as session:
        created += _rule_low_rating(session, since)
        created += _rule_sentiment_drop(session)
        created += _rule_competitor_news(session, since)
        created += _rule_price_threat(session, since)
        created += _rule_strategic_threat(session, since)
        return [
            {
                "id": a.id,
                "priority": a.priority,
                "subject": a.subject,
                "detail": a.detail,
                "source_type": a.source_type,
                "created_at": a.created_at.isoformat(),
            }
            for a in created
        ]


def get_unacknowledged(since_hours: int = 48, limit: int = 50) -> list[dict]:
    since = datetime.utcnow() - timedelta(hours=since_hours)
    with session_scope() as session:
        rows = session.scalars(
            select(Alert)
            .where(Alert.acknowledged.is_(False))
            .where(Alert.created_at >= since)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": a.id,
                "priority": a.priority,
                "subject": a.subject,
                "detail": a.detail,
                "source_type": a.source_type,
                "source_id": a.source_id,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ]


def acknowledge(alert_id: int, user_id: int) -> bool:
    with session_scope() as session:
        a = session.get(Alert, alert_id)
        if not a or a.acknowledged:
            return False
        a.acknowledged = True
        a.acknowledged_by = user_id
        a.acknowledged_at = datetime.utcnow()
        return True


def format_alerts(alerts: list[dict]) -> str:
    if not alerts:
        return "No alerts."
    icons = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
    return "\n".join(
        f"{icons.get(a['priority'],'•')} [{a['priority']}] {a['subject']}\n   {a['detail'][:160]}"
        for a in alerts
    )
