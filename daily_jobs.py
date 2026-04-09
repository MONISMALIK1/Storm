"""
daily_jobs.py — Daily Intelligence Collection Pipeline
=======================================================
Defines all daily search jobs that the scheduler runs automatically.
Each job specifies:
  - What to search
  - What database to save to
  - How to classify the data
  - Priority / frequency

The scheduler picks these up and runs them on a daily cadence.
"""

DAILY_JOBS = [
    # ── TOW Store Reviews ─────────────────────────────────────
    {
        "job_id": "tow_reviews_pragathi",
        "category": "reviews",
        "label": "TOW Pragathi Nagar Reviews",
        "queries": [
            "The Organic World Pragathi Nagar Hyderabad customer review",
            "The Organic World Kukatpally review rating 2024 2025",
        ],
        "save_as": "review",
        "store_location": "Pragathi Nagar - Kukatpally",
        "frequency": "daily",
        "priority": 1,
    },
    {
        "job_id": "tow_reviews_kokapet",
        "category": "reviews",
        "label": "TOW Kokapet Reviews",
        "queries": [
            "The Organic World Kokapet Narsingi Hyderabad review",
            "TOW organic store Kokapet customer feedback",
        ],
        "save_as": "review",
        "store_location": "Kokapet - Narsingi",
        "frequency": "daily",
        "priority": 1,
    },
    {
        "job_id": "tow_reviews_hafeezpet",
        "category": "reviews",
        "label": "TOW Hafeezpet Reviews",
        "queries": [
            "The Organic World Hafeezpet Hyderabad review rating",
            "organic store Hafeezpet TOW customer opinion",
        ],
        "save_as": "review",
        "store_location": "Hafeezpet - Spring Valley Road",
        "frequency": "daily",
        "priority": 1,
    },
    {
        "job_id": "tow_reviews_general",
        "category": "reviews",
        "label": "TOW Hyderabad General Reviews",
        "queries": [
            "The Organic World Hyderabad reviews 2025",
            "theorganicworld.com Hyderabad customer feedback",
            "TOW Hyderabad organic store experience review",
        ],
        "save_as": "review",
        "store_location": "Multiple Stores - Hyderabad",
        "frequency": "daily",
        "priority": 1,
    },

    # ── Competitor Intelligence ───────────────────────────────
    {
        "job_id": "competitor_24mantra",
        "category": "competitors",
        "label": "24 Mantra Hyderabad Intelligence",
        "queries": [
            "24 Mantra Organic store Hyderabad 2025 expansion",
            "24 Mantra ITC Hyderabad organic retail news",
            "Sresta 24 Mantra Hyderabad customer review rating",
        ],
        "save_as": "news",
        "relevance_tag": "competitor",
        "frequency": "daily",
        "priority": 2,
    },
    {
        "job_id": "competitor_naturally_yours",
        "category": "competitors",
        "label": "Naturally Yours Hyderabad Intelligence",
        "queries": [
            "Naturally Yours organic store Hyderabad 2025",
            "Naturally Yours Hyderabad delivery review price",
        ],
        "save_as": "news",
        "relevance_tag": "competitor",
        "frequency": "daily",
        "priority": 2,
    },
    {
        "job_id": "competitor_new_entrants",
        "category": "competitors",
        "label": "New Organic Store Entrants Hyderabad",
        "queries": [
            "new organic grocery store opening Hyderabad 2025",
            "organic retail launch Hyderabad Telangana 2025",
            "organic food startup Hyderabad funding expansion",
        ],
        "save_as": "intel",
        "intel_type": "threat",
        "frequency": "daily",
        "priority": 2,
    },
    {
        "job_id": "competitor_blinkit_organic",
        "category": "competitors",
        "label": "Quick Commerce Organic Hyderabad",
        "queries": [
            "Blinkit Zepto organic grocery Hyderabad 2025",
            "quick commerce organic delivery 10 minutes Hyderabad",
        ],
        "save_as": "news",
        "relevance_tag": "competitor",
        "frequency": "daily",
        "priority": 2,
    },

    # ── Market Trends & News ──────────────────────────────────
    {
        "job_id": "market_organic_trend",
        "category": "market",
        "label": "Organic Market Trends India",
        "queries": [
            "organic food market India growth 2025 trend",
            "organic grocery consumer behaviour India 2025",
            "chemical free products India demand growth",
        ],
        "save_as": "news",
        "relevance_tag": "market_trend",
        "frequency": "daily",
        "priority": 3,
    },
    {
        "job_id": "market_millet_trend",
        "category": "market",
        "label": "Millet Trend Hyderabad",
        "queries": [
            "millet products Hyderabad consumer trend 2025",
            "millets organic Hyderabad demand growth",
        ],
        "save_as": "intel",
        "intel_type": "opportunity",
        "frequency": "daily",
        "priority": 3,
    },
    {
        "job_id": "market_tow_news",
        "category": "market",
        "label": "TOW Corporate News",
        "queries": [
            "The Organic World Nimida Group news 2025",
            "TOW organic Hyderabad expansion store opening",
            "Gaurav Manchanda The Organic World interview",
        ],
        "save_as": "news",
        "relevance_tag": "TOW",
        "frequency": "daily",
        "priority": 1,
    },

    # ── Pricing Intelligence ──────────────────────────────────
    {
        "job_id": "pricing_organic_staples",
        "category": "pricing",
        "label": "Organic Staple Price Monitoring",
        "queries": [
            "organic turmeric 100g price Hyderabad online 2025",
            "organic rice 1kg price comparison Hyderabad",
            "24 Mantra organic flour price BigBasket Hyderabad",
        ],
        "save_as": "news",
        "relevance_tag": "market_trend",
        "frequency": "daily",
        "priority": 3,
    },

    # ── Customer Sentiment & Pain Points ─────────────────────
    {
        "job_id": "sentiment_complaints",
        "category": "sentiment",
        "label": "Customer Complaints & Pain Points",
        "queries": [
            "organic store Hyderabad complaint bad experience",
            "The Organic World negative review problem",
            "organic grocery delivery issue Hyderabad 2025",
        ],
        "save_as": "intel",
        "intel_type": "customer_pain_point",
        "frequency": "daily",
        "priority": 2,
    },
    {
        "job_id": "sentiment_social",
        "category": "sentiment",
        "label": "Social Sentiment TOW Hyderabad",
        "queries": [
            "The Organic World Hyderabad twitter reddit mention",
            "TOW organic Hyderabad social media review",
            "organic grocery Hyderabad customer recommendation 2025",
        ],
        "save_as": "review",
        "store_location": "Multiple Stores - Hyderabad",
        "frequency": "daily",
        "priority": 2,
    },

    # ── Regulatory & Policy ───────────────────────────────────
    {
        "job_id": "regulation_organic",
        "category": "regulation",
        "label": "Organic Food Regulation India",
        "queries": [
            "organic food certification regulation India 2025 FSSAI",
            "organic retail policy Telangana Hyderabad",
        ],
        "save_as": "news",
        "relevance_tag": "regulation",
        "frequency": "weekly",
        "priority": 4,
    },
]

def get_daily_jobs() -> list[dict]:
    """Return only jobs that should run today (daily + weekly on Monday)."""
    from datetime import datetime
    today_weekday = datetime.now().weekday()  # 0=Monday
    return [
        j for j in DAILY_JOBS
        if j.get("frequency") == "daily"
        or (j.get("frequency") == "weekly" and today_weekday == 0)
    ]

def get_jobs_by_priority(max_priority: int = 3) -> list[dict]:
    """Return jobs up to a given priority level, sorted by priority."""
    jobs = get_daily_jobs()
    return sorted(
        [j for j in jobs if j.get("priority", 99) <= max_priority],
        key=lambda j: j.get("priority", 99),
    )