"""Sentiment scoring, keyword extraction, and rolling trend computation."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import NewsItem, Review
from .dedup_simhash import tokens

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
except Exception:
    _vader = None

_POS_LEX = {
    "good", "great", "excellent", "amazing", "love", "best", "fresh",
    "quality", "happy", "recommend", "fantastic", "wonderful", "perfect",
    "clean", "friendly", "affordable", "organic", "healthy",
}
_NEG_LEX = {
    "bad", "terrible", "awful", "worst", "hate", "poor", "stale",
    "expensive", "overpriced", "rude", "slow", "rotten", "disappointed",
    "dirty", "complaint", "problem", "issue", "refund", "fake",
}


def sentiment_score(text: str) -> float:
    """Return compound score in [-1, 1]. Uses VADER if available."""
    if not text:
        return 0.0
    if _vader is not None:
        return float(_vader.polarity_scores(text)["compound"])
    toks = tokens(text)
    if not toks:
        return 0.0
    pos = sum(1 for t in toks if t in _POS_LEX)
    neg = sum(1 for t in toks if t in _NEG_LEX)
    if pos == neg == 0:
        return 0.0
    return (pos - neg) / max(pos + neg, 1)


def sentiment_label(score: float, rating: Optional[float] = None) -> str:
    if rating is not None:
        if rating >= 4:
            return "positive"
        if rating <= 2:
            return "negative"
        if rating == 3:
            return "neutral"
    if score >= 0.15:
        return "positive"
    if score <= -0.15:
        return "negative"
    return "neutral"


def keyword_counts(texts: list[str], top_n: int = 20) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for t in texts:
        counter.update(tokens(t))
    return counter.most_common(top_n)


def review_trend(session: Session, days: int = 30) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = session.scalars(
        select(Review).where(Review.created_at >= cutoff)
    ).all()
    if not rows:
        return {"days": days, "count": 0, "avg_rating": None, "sentiment_split": {}}
    ratings = [r.rating for r in rows if r.rating is not None]
    split = Counter(r.sentiment for r in rows if r.sentiment)
    return {
        "days": days,
        "count": len(rows),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "sentiment_split": dict(split),
        "by_store": dict(Counter(r.store_location for r in rows).most_common(10)),
    }


def news_volume_by_tag(session: Session, days: int = 7) -> dict[str, int]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = session.execute(
        select(NewsItem.relevance_tag, func.count())
        .where(NewsItem.created_at >= cutoff)
        .group_by(NewsItem.relevance_tag)
    ).all()
    return {tag: int(n) for tag, n in rows}


def extract_keywords(text: str, top_n: int = 15) -> list[tuple[str, int]]:
    """Extract top keywords from combined text. Alias for keyword_counts on a single string."""
    return keyword_counts([text], top_n=top_n)


def top_keywords(texts: list[str], top_n: int = 15) -> list[tuple[str, int]]:
    """Convenience wrapper for multiple texts."""
    return keyword_counts(texts, top_n=top_n)


def enrich_review(text: str, rating: Optional[float]) -> tuple[float, str]:
    score = sentiment_score(text)
    label = sentiment_label(score, rating)
    return score, label


def enrich_news(text: str) -> tuple[float, str]:
    score = sentiment_score(text)
    return score, sentiment_label(score)
