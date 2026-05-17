"""Pydantic response/request schemas for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str


class UserPublic(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = "viewer"


class ReviewOut(BaseModel):
    id: int
    store_location: str
    store_city: Optional[str] = None
    product_name: Optional[str] = None
    reviewer_name: Optional[str] = None
    rating: Optional[float] = None
    review_text: str
    source: str
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NewsOut(BaseModel):
    id: int
    headline: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: str
    relevance_tag: str
    sentiment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CompetitorOut(BaseModel):
    id: int
    competitor_name: str
    location: Optional[str] = None
    category: Optional[str] = None
    strengths: Optional[str] = None
    weaknesses: Optional[str] = None
    price_positioning: Optional[str] = None
    notable_products: Optional[str] = None
    online_presence: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PriceOut(BaseModel):
    id: int
    product_name: str
    tow_price: float
    competitor_name: str
    competitor_price: float
    price_diff_pct: float
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class IntelOut(BaseModel):
    id: int
    intel_type: str
    subject: str
    detail: str
    strategic_implication: Optional[str] = None
    source: str
    created_at: datetime

    class Config:
        from_attributes = True


class AlertOut(BaseModel):
    id: int
    priority: str
    subject: str
    detail: str
    source_type: str
    source_id: Optional[int] = None
    acknowledged: bool
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardSummary(BaseModel):
    review_count: int
    avg_rating: Optional[float]
    sentiment_split: dict
    news_24h: int
    intel_24h: int
    competitor_count: int
    pricing_records: int
    unacknowledged_alerts: int
    top_keywords: list[tuple[str, int]]


class AppReviewOut(BaseModel):
    id: int
    source: str
    reviewer: Optional[str] = None
    star_rating: Optional[int] = None
    review_text: str
    sentiment: Optional[str] = None
    rating_implied: Optional[float] = None
    topic: Optional[str] = None
    summary: Optional[str] = None
    review_date: Optional[str] = None
    thumbs_up: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ProductOut(BaseModel):
    id: int
    product_id: Optional[str] = None
    product_name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    min_price_inr: Optional[float] = None
    max_price_inr: Optional[float] = None
    discount_pct: Optional[float] = None
    stock_status: Optional[str] = None
    avg_rating: Optional[float] = None
    review_count: Optional[int] = None
    unit: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AppSummary(BaseModel):
    total_app_reviews: int
    avg_star_rating: Optional[float]
    sentiment_split: dict          # {positive, neutral, negative}
    topic_split: dict              # {app_ux, product_quality, ...}
    platform_split: dict           # {app_store, play_store}
    safety_complaint_count: int    # reviews mentioning spoilt/rotten/stale etc.
    nps_proxy: Optional[float]     # recommend-rate minus uninstall-rate


class ProductSummary(BaseModel):
    total_products: int
    in_stock: int
    out_of_stock: int
    categories: list[dict]         # [{category, count, avg_price}]
    avg_discount_pct: Optional[float]
    top_discounted: list[dict]     # top 5 products by discount
