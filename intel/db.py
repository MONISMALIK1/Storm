"""Unified SQLite data layer for the intelligence pipeline."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    create_engine, event,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker,
)

DB_PATH = os.environ.get("INTEL_DB_PATH", "intel.db")
ENGINE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(ENGINE_URL, future=True, echo=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def now() -> datetime:
    return datetime.utcnow()


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_location: Mapped[str] = mapped_column(String(200), index=True)
    store_city: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    store_address: Mapped[Optional[str]] = mapped_column(Text)
    store_url: Mapped[Optional[str]] = mapped_column(Text)
    product_name: Mapped[Optional[str]] = mapped_column(String(200))
    reviewer_name: Mapped[Optional[str]] = mapped_column(String(120))
    rating: Mapped[Optional[float]] = mapped_column(Float, index=True)
    review_text: Mapped[str] = mapped_column(Text)
    review_date: Mapped[Optional[str]] = mapped_column(String(40))
    helpful_votes: Mapped[Optional[int]] = mapped_column(Integer)
    owner_response: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(60), index=True)
    sentiment: Mapped[Optional[str]] = mapped_column(String(16), index=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    simhash: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class Competitor(Base):
    __tablename__ = "competitors"
    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_name: Mapped[str] = mapped_column(String(160), index=True)
    location: Mapped[Optional[str]] = mapped_column(String(200))
    category: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    strengths: Mapped[Optional[str]] = mapped_column(Text)
    weaknesses: Mapped[Optional[str]] = mapped_column(Text)
    price_positioning: Mapped[Optional[str]] = mapped_column(String(40))
    notable_products: Mapped[Optional[str]] = mapped_column(Text)
    online_presence: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(80))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class NewsItem(Base):
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(primary_key=True)
    headline: Mapped[str] = mapped_column(String(400), index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(120), index=True)
    relevance_tag: Mapped[str] = mapped_column(String(40), index=True)
    sentiment: Mapped[Optional[str]] = mapped_column(String(16))
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    simhash: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class PriceRecord(Base):
    __tablename__ = "pricing"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_name: Mapped[str] = mapped_column(String(200), index=True)
    tow_price: Mapped[float] = mapped_column(Float)
    competitor_name: Mapped[str] = mapped_column(String(160), index=True)
    competitor_price: Mapped[float] = mapped_column(Float)
    price_diff_pct: Mapped[float] = mapped_column(Float)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(120))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class IntelSignal(Base):
    __tablename__ = "intel"
    id: Mapped[int] = mapped_column(primary_key=True)
    intel_type: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(240), index=True)
    detail: Mapped[str] = mapped_column(Text)
    strategic_implication: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    priority: Mapped[str] = mapped_column(String(10), index=True)
    subject: Mapped[str] = mapped_column(String(240))
    detail: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), index=True)
    source_id: Mapped[Optional[int]] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    acknowledged_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(40))
    target_id: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class AppReview(Base):
    """App Store / Play Store review."""
    __tablename__ = "app_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)          # app_store | play_store
    reviewer: Mapped[Optional[str]] = mapped_column(String(120))
    star_rating: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    review_text: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[Optional[str]] = mapped_column(String(16), index=True)
    rating_implied: Mapped[Optional[float]] = mapped_column(Float)
    topic: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    review_date: Mapped[Optional[str]] = mapped_column(String(40))
    thumbs_up: Mapped[Optional[int]] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class Product(Base):
    """TOW product catalogue."""
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    product_name: Mapped[str] = mapped_column(String(300), index=True)
    brand: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    category: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    category_id: Mapped[Optional[str]] = mapped_column(String(40))
    min_price_inr: Mapped[Optional[float]] = mapped_column(Float)
    max_price_inr: Mapped[Optional[float]] = mapped_column(Float)
    discount_pct: Mapped[Optional[float]] = mapped_column(Float)
    discount_type: Mapped[Optional[str]] = mapped_column(String(40))
    unit: Mapped[Optional[str]] = mapped_column(String(60))
    stock_status: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    avg_rating: Mapped[Optional[float]] = mapped_column(Float)
    review_count: Mapped[Optional[int]] = mapped_column(Integer)
    variations_count: Mapped[Optional[int]] = mapped_column(Integer)
    slug: Mapped[Optional[str]] = mapped_column(String(300))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


Index("ix_reviews_created_rating", Review.created_at, Review.rating)
Index("ix_news_created_tag", NewsItem.created_at, NewsItem.relevance_tag)
Index("ix_alerts_unack_priority", Alert.acknowledged, Alert.priority, Alert.created_at)
Index("ix_app_reviews_source_topic", AppReview.source, AppReview.topic)
Index("ix_products_category_stock", Product.category, Product.stock_status)


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
