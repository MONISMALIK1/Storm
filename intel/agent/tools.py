"""
Tool definitions and executors for the CI Agent.

Each tool is defined as an Anthropic-compatible JSON schema dict (for the API)
plus a paired Python executor function.  The executor is called when Claude
returns a tool_use block with that tool's name.
"""
from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from typing import Any


# ── Tool schema definitions (passed to the Anthropic API) ─────────────────────

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "query_reviews",
        "description": (
            "Query customer reviews from the unified intelligence database. "
            "Supports filtering by store location, sentiment label, minimum rating, "
            "source, and time window. Always use this tool when the user asks about "
            "customer feedback, ratings, review trends, or specific review incidents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store": {
                    "type": "string",
                    "description": "Filter by store_location (partial match, e.g. 'Banjara')",
                },
                "sentiment": {
                    "type": "string",
                    "enum": ["positive", "neutral", "negative"],
                    "description": "Filter by sentiment label",
                },
                "min_rating": {
                    "type": "number",
                    "description": "Only include reviews with rating >= this value",
                },
                "max_rating": {
                    "type": "number",
                    "description": "Only include reviews with rating <= this value",
                },
                "source": {
                    "type": "string",
                    "description": "Filter by source, e.g. 'Google Maps'",
                },
                "days": {
                    "type": "integer",
                    "description": "Only include reviews created in the last N days (default 30)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return (default 50, max 200)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_news",
        "description": (
            "Query competitor and market news from the database. Use this when the "
            "user asks about recent competitor activity, market news, industry events, "
            "or any news signals about the competitive landscape."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Filter by relevance_tag (e.g. 'competitor', 'market')",
                },
                "sentiment": {
                    "type": "string",
                    "enum": ["positive", "neutral", "negative"],
                },
                "days": {
                    "type": "integer",
                    "description": "Last N days of news (default 7)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return (default 30)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_competitors",
        "description": (
            "Query competitor profile data: category, price positioning, strengths, "
            "weaknesses, and notable products. Use this for competitive landscape "
            "analysis or when the user asks about a specific competitor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Partial competitor name to filter (e.g. 'BigBasket')",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by product category",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default 20)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_pricing",
        "description": (
            "Query TOW vs competitor pricing comparisons. price_diff_pct is computed as "
            "(tow_price - competitor_price) / competitor_price * 100: "
            "positive means TOW is more expensive, negative means TOW is cheaper. "
            "A value > 15 indicates a price threat. Use for pricing gap analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": "Filter by product name (partial match)",
                },
                "competitor": {
                    "type": "string",
                    "description": "Filter by competitor name",
                },
                "min_diff_pct": {
                    "type": "number",
                    "description": "Only include rows where TOW is at least this % more expensive",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows (default 30)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_intel",
        "description": (
            "Query strategic intelligence signals: opportunities, threats, market trends, "
            "and other forward-looking intelligence. Use for strategy sessions and "
            "when the user asks about threats or market opportunities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intel_type": {
                    "type": "string",
                    "enum": ["opportunity", "threat", "trend", "market"],
                    "description": "Filter by signal type",
                },
                "days": {
                    "type": "integer",
                    "description": "Last N days (default 30)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows (default 20)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_dashboard_summary",
        "description": (
            "Get the KPI dashboard summary: total review count, average star rating, "
            "news and intel counts for the last 24h, competitor count, unacknowledged "
            "alert count, sentiment distribution (positive/neutral/negative), and "
            "top 15 keywords from recent reviews. Use this as the starting point for "
            "any health check or executive brief."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_unacked_alerts",
        "description": (
            "Retrieve all currently unacknowledged alerts, sorted by priority "
            "(CRITICAL first). Each alert includes priority, subject, detail, "
            "source_type, and creation time. Always call this when generating "
            "a briefing or when the user asks about open issues."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "Look back window in hours (default 168 = 7 days)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                    "description": "Filter to a specific priority level",
                },
            },
            "required": [],
        },
    },
    {
        "name": "run_alert_scan",
        "description": (
            "Trigger the alert detection engine to sweep recent data and create "
            "new alerts according to the 5 built-in rules. This is idempotent — "
            "running it multiple times will not create duplicate alerts (fingerprint "
            "deduplication). Returns a list of newly created alerts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "run_ingest",
        "description": (
            "Trigger a full ingestion pass: reads all CSV files and the gmap SQLite DB, "
            "deduplicates via content_hash and SimHash, enriches with sentiment analysis, "
            "and inserts new rows into the unified intel.db. Returns counts per source. "
            "This can take 10-60 seconds depending on data volume."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "analyze_sentiment_trend",
        "description": (
            "Compute a detailed sentiment trend analysis: 7-day vs 30-day average ratings, "
            "trend direction (improving/declining/stable), top negative themes from recent "
            "reviews, and store-level breakdowns. Use this when the user asks about "
            "sentiment changes over time or wants to understand if things are getting better."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store": {
                    "type": "string",
                    "description": "Limit analysis to a specific store location",
                },
            },
            "required": [],
        },
    },
]


# ── Executor functions ─────────────────────────────────────────────────────────

def _safe_json(obj: Any) -> str:
    """Serialize to compact JSON, handling non-serializable types."""
    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=_default, ensure_ascii=False)


def _exec_query_reviews(args: dict) -> str:
    try:
        from sqlalchemy import select, and_
        from intel.db import Review, session_scope
        from datetime import timedelta

        store = args.get("store")
        sentiment = args.get("sentiment")
        min_rating = args.get("min_rating")
        max_rating = args.get("max_rating")
        source = args.get("source")
        days = int(args.get("days", 30))
        limit = min(int(args.get("limit", 50)), 200)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with session_scope() as s:
            q = select(Review).where(Review.created_at >= cutoff)
            if store:
                q = q.where(Review.store_location.ilike(f"%{store}%"))
            if sentiment:
                q = q.where(Review.sentiment == sentiment)
            if min_rating is not None:
                q = q.where(Review.rating >= min_rating)
            if max_rating is not None:
                q = q.where(Review.rating <= max_rating)
            if source:
                q = q.where(Review.source.ilike(f"%{source}%"))
            q = q.order_by(Review.created_at.desc()).limit(limit)

            rows = s.scalars(q).all()
            results = [
                {
                    "id": r.id,
                    "store": r.store_location,
                    "rating": r.rating,
                    "sentiment": r.sentiment,
                    "sentiment_score": r.sentiment_score,
                    "text": (r.review_text or "")[:500],
                    "reviewer": r.reviewer_name,
                    "source": r.source,
                    "date": r.review_date,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
        return _safe_json({"count": len(results), "reviews": results})
    except Exception as e:
        return _safe_json({"error": str(e), "trace": traceback.format_exc()[-500:]})


def _exec_query_news(args: dict) -> str:
    try:
        from sqlalchemy import select
        from intel.db import News, session_scope
        from datetime import timedelta

        tag = args.get("tag")
        sentiment = args.get("sentiment")
        days = int(args.get("days", 7))
        limit = min(int(args.get("limit", 30)), 100)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with session_scope() as s:
            q = select(News).where(News.created_at >= cutoff)
            if tag:
                q = q.where(News.relevance_tag.ilike(f"%{tag}%"))
            if sentiment:
                q = q.where(News.sentiment == sentiment)
            q = q.order_by(News.created_at.desc()).limit(limit)
            rows = s.scalars(q).all()
            results = [
                {
                    "id": n.id,
                    "headline": n.headline,
                    "summary": (n.summary or "")[:300],
                    "source": n.source,
                    "url": n.url,
                    "tag": n.relevance_tag,
                    "sentiment": n.sentiment,
                    "sentiment_score": n.sentiment_score,
                    "created_at": n.created_at,
                }
                for n in rows
            ]
        return _safe_json({"count": len(results), "news": results})
    except Exception as e:
        return _safe_json({"error": str(e)})


def _exec_query_competitors(args: dict) -> str:
    try:
        from sqlalchemy import select
        from intel.db import Competitor, session_scope

        name = args.get("name")
        category = args.get("category")
        limit = min(int(args.get("limit", 20)), 50)

        with session_scope() as s:
            q = select(Competitor)
            if name:
                q = q.where(Competitor.competitor_name.ilike(f"%{name}%"))
            if category:
                q = q.where(Competitor.category.ilike(f"%{category}%"))
            q = q.order_by(Competitor.competitor_name).limit(limit)
            rows = s.scalars(q).all()
            results = [
                {
                    "id": c.id,
                    "name": c.competitor_name,
                    "category": c.category,
                    "price_positioning": c.price_positioning,
                    "strengths": c.strengths,
                    "weaknesses": c.weaknesses,
                    "notable_products": c.notable_products,
                }
                for c in rows
            ]
        return _safe_json({"count": len(results), "competitors": results})
    except Exception as e:
        return _safe_json({"error": str(e)})


def _exec_query_pricing(args: dict) -> str:
    try:
        from sqlalchemy import select
        from intel.db import Pricing, session_scope

        product = args.get("product")
        competitor = args.get("competitor")
        min_diff = args.get("min_diff_pct")
        limit = min(int(args.get("limit", 30)), 100)

        with session_scope() as s:
            q = select(Pricing)
            if product:
                q = q.where(Pricing.product_name.ilike(f"%{product}%"))
            if competitor:
                q = q.where(Pricing.competitor_name.ilike(f"%{competitor}%"))
            if min_diff is not None:
                q = q.where(Pricing.price_diff_pct >= float(min_diff))
            q = q.order_by(Pricing.price_diff_pct.desc()).limit(limit)
            rows = s.scalars(q).all()
            results = [
                {
                    "id": p.id,
                    "product": p.product_name,
                    "competitor": p.competitor_name,
                    "tow_price": p.tow_price,
                    "competitor_price": p.competitor_price,
                    "diff_pct": p.price_diff_pct,
                    "notes": p.notes,
                }
                for p in rows
            ]
        return _safe_json({"count": len(results), "pricing": results})
    except Exception as e:
        return _safe_json({"error": str(e)})


def _exec_query_intel(args: dict) -> str:
    try:
        from sqlalchemy import select
        from intel.db import Intel, session_scope
        from datetime import timedelta

        intel_type = args.get("intel_type")
        days = int(args.get("days", 30))
        limit = min(int(args.get("limit", 20)), 100)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with session_scope() as s:
            q = select(Intel).where(Intel.created_at >= cutoff)
            if intel_type:
                q = q.where(Intel.intel_type == intel_type)
            q = q.order_by(Intel.created_at.desc()).limit(limit)
            rows = s.scalars(q).all()
            results = [
                {
                    "id": i.id,
                    "subject": i.subject,
                    "detail": (i.detail or "")[:400],
                    "type": i.intel_type,
                    "strategic_implication": i.strategic_implication,
                    "source": i.source,
                    "created_at": i.created_at,
                }
                for i in rows
            ]
        return _safe_json({"count": len(results), "intel": results})
    except Exception as e:
        return _safe_json({"error": str(e)})


def _exec_get_dashboard_summary(_args: dict) -> str:
    try:
        from intel.analysis import review_trend, news_volume_by_tag, top_keywords
        from intel.db import Review, News, Competitor, Pricing, Alert, session_scope
        from sqlalchemy import select, func
        from datetime import timedelta

        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)

        with session_scope() as s:
            review_count = s.scalar(select(func.count()).select_from(Review)) or 0
            avg_rating = s.scalar(select(func.avg(Review.rating)).where(Review.rating.isnot(None))) or 0
            news_24h = s.scalar(select(func.count()).select_from(News).where(News.created_at >= cutoff_24h)) or 0
            from intel.db import Intel
            intel_24h = s.scalar(select(func.count()).select_from(Intel).where(Intel.created_at >= cutoff_24h)) or 0
            competitor_count = s.scalar(select(func.count()).select_from(Competitor)) or 0
            unacked = s.scalar(
                select(func.count()).select_from(Alert).where(Alert.acknowledged == False)
            ) or 0

            # Sentiment split
            sentiments = s.execute(
                select(Review.sentiment, func.count()).group_by(Review.sentiment)
            ).all()
            split = {row[0]: row[1] for row in sentiments if row[0]}

            # Top keywords from 500 most recent reviews
            recent_texts = [
                r.review_text
                for r in s.scalars(
                    select(Review.review_text)
                    .where(Review.review_text.isnot(None))
                    .order_by(Review.created_at.desc())
                    .limit(500)
                ).all()
            ]

        from intel.analysis import extract_keywords
        kw = extract_keywords(" ".join(recent_texts), top_n=15)

        return _safe_json({
            "review_count": review_count,
            "avg_rating": round(float(avg_rating), 2) if avg_rating else None,
            "news_24h": news_24h,
            "intel_24h": intel_24h,
            "competitor_count": competitor_count,
            "unacknowledged_alerts": unacked,
            "sentiment_split": split,
            "top_keywords": kw,
        })
    except Exception as e:
        return _safe_json({"error": str(e), "trace": traceback.format_exc()[-500:]})


def _exec_get_unacked_alerts(args: dict) -> str:
    try:
        from intel.alerts import get_unacknowledged
        hours = int(args.get("hours", 168))
        priority = args.get("priority")
        alerts = get_unacknowledged(since_hours=hours)
        if priority:
            alerts = [a for a in alerts if a.get("priority") == priority]
        return _safe_json({"count": len(alerts), "alerts": alerts})
    except Exception as e:
        return _safe_json({"error": str(e)})


def _exec_run_alert_scan(_args: dict) -> str:
    try:
        from intel.alerts import run_detection
        from intel.db import init_db
        init_db()
        new = run_detection()
        return _safe_json({"new_alert_count": len(new), "new_alerts": new})
    except Exception as e:
        return _safe_json({"error": str(e)})


def _exec_run_ingest(_args: dict) -> str:
    try:
        from intel.ingest import ingest_all
        from intel.db import init_db
        init_db()
        result = ingest_all()
        return _safe_json(result)
    except Exception as e:
        return _safe_json({"error": str(e)})


def _exec_analyze_sentiment_trend(args: dict) -> str:
    try:
        from sqlalchemy import select, func
        from intel.db import Review, session_scope
        from datetime import timedelta
        import statistics

        store = args.get("store")
        now = datetime.now(timezone.utc)
        cutoff_7d = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=30)

        with session_scope() as s:
            base_q = select(Review).where(Review.rating.isnot(None))
            if store:
                base_q = base_q.where(Review.store_location.ilike(f"%{store}%"))

            rows_30d = s.scalars(base_q.where(Review.created_at >= cutoff_30d)).all()
            rows_7d = [r for r in rows_30d if r.created_at and r.created_at >= cutoff_7d]

            def _avg(rows):
                vals = [r.rating for r in rows if r.rating is not None]
                return round(statistics.mean(vals), 2) if vals else None

            avg_7d = _avg(rows_7d)
            avg_30d = _avg(rows_30d)

            trend = "stable"
            if avg_7d and avg_30d:
                diff = avg_7d - avg_30d
                if diff >= 0.1:
                    trend = "improving"
                elif diff <= -0.1:
                    trend = "declining"

            # Top negative themes (simple word frequency on negative reviews)
            neg_texts = [
                r.review_text for r in rows_7d
                if r.sentiment == "negative" and r.review_text
            ]
            from intel.analysis import extract_keywords
            neg_themes = extract_keywords(" ".join(neg_texts), top_n=10) if neg_texts else []

            # Store breakdown
            store_ratings: dict = {}
            for r in rows_30d:
                loc = r.store_location or "unknown"
                store_ratings.setdefault(loc, []).append(r.rating)
            store_breakdown = {
                loc: round(statistics.mean(ratings), 2)
                for loc, ratings in store_ratings.items()
            }

        return _safe_json({
            "period": "7d vs 30d",
            "avg_rating_7d": avg_7d,
            "avg_rating_30d": avg_30d,
            "trend": trend,
            "review_count_7d": len(rows_7d),
            "review_count_30d": len(rows_30d),
            "top_negative_themes_7d": neg_themes,
            "store_breakdown_30d": store_breakdown,
        })
    except Exception as e:
        return _safe_json({"error": str(e), "trace": traceback.format_exc()[-500:]})


# ── Dispatch table ─────────────────────────────────────────────────────────────

_EXECUTORS: dict[str, Any] = {
    "query_reviews": _exec_query_reviews,
    "query_news": _exec_query_news,
    "query_competitors": _exec_query_competitors,
    "query_pricing": _exec_query_pricing,
    "query_intel": _exec_query_intel,
    "get_dashboard_summary": _exec_get_dashboard_summary,
    "get_unacked_alerts": _exec_get_unacked_alerts,
    "run_alert_scan": _exec_run_alert_scan,
    "run_ingest": _exec_run_ingest,
    "analyze_sentiment_trend": _exec_analyze_sentiment_trend,
}


def execute_tool(name: str, tool_input: dict) -> str:
    """Dispatch a tool_use block to the correct executor and return a JSON string."""
    executor = _EXECUTORS.get(name)
    if executor is None:
        return _safe_json({"error": f"Unknown tool: {name}"})
    try:
        return executor(tool_input)
    except Exception as e:
        return _safe_json({"error": f"Tool {name} raised: {e}"})
