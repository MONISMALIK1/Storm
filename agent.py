"""
agent.py — The Organic World Hyderabad | Competitive Intelligence Agent
========================================================================
A LangChain ReAct agent powered by local Ollama that acts as a full
competitive intelligence system for The Organic World (TOW) Hyderabad.

It collects, stores, and analyses:
  • Customer reviews (TOW + competitors)
  • Competitor profiles (prices, strengths, weaknesses)
  • Market news & press mentions
  • Pricing intelligence
  • Store-level performance data
  • Strategic SWOT signals

All data is persisted across 5 specialised CSV files.
Web search uses DuckDuckGo — zero API keys required.
"""

import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

from langchain.agents import AgentExecutor, create_react_agent
from langchain.tools import tool
from langchain_core.prompts import PromptTemplate
from langchain_ollama import ChatOllama

# Deduplication engine (graceful fallback if module not loaded yet)
try:
    from dedup import check_and_mark
except ImportError:
    def check_and_mark(ns, content):  # noqa
        return False  # never deduplicate if module missing

# ──────────────────────────────────────────────────────────────
# File definitions
# ──────────────────────────────────────────────────────────────

FILES = {
    "reviews":     "tow_reviews.csv",
    "competitors": "tow_competitors.csv",
    "news":        "tow_news.csv",
    "pricing":     "tow_pricing.csv",
    "intel":       "tow_intel.csv",
}

SCHEMAS = {
    "reviews": [
        "id", "store_location", "product_name", "reviewer_name",
        "rating", "review_text", "source", "sentiment", "timestamp",
    ],
    "competitors": [
        "id", "competitor_name", "location", "category", "strengths",
        "weaknesses", "price_positioning", "notable_products",
        "online_presence", "source", "timestamp",
    ],
    "news": [
        "id", "headline", "summary", "url", "source",
        "relevance_tag", "timestamp",
    ],
    "pricing": [
        "id", "product_name", "tow_price", "competitor_name",
        "competitor_price", "price_diff_pct", "notes", "source", "timestamp",
    ],
    "intel": [
        "id", "intel_type", "subject", "detail",
        "strategic_implication", "source", "timestamp",
    ],
}


# ──────────────────────────────────────────────────────────────
# Generic CSV helpers
# ──────────────────────────────────────────────────────────────

def _ensure(key: str) -> None:
    path = FILES[key]
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=SCHEMAS[key]).writeheader()


def _read(key: str) -> list[dict]:
    _ensure(key)
    with open(FILES[key], "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(key: str, rows: list[dict]) -> None:
    with open(FILES[key], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SCHEMAS[key])
        w.writeheader()
        w.writerows(rows)


def _append(key: str, row: dict) -> dict:
    rows = _read(key)
    row["id"] = max((int(r["id"]) for r in rows), default=0) + 1
    row["timestamp"] = datetime.now().isoformat(timespec="seconds")
    rows.append(row)
    _write(key, rows)
    return row


# ──────────────────────────────────────────────────────────────
# DuckDuckGo search (no API key)
# ──────────────────────────────────────────────────────────────

def _ddg(query: str, n: int = 6) -> list[dict]:
    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        ),
        "Accept-Language": "en-IN,en;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return [{"error": str(exc)}]

    results = []
    blocks = re.findall(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL,
    )
    for href, title_html, snippet_html in blocks[:n]:
        results.append({
            "title":   re.sub(r"<[^>]+>", "", title_html).strip(),
            "url":     href,
            "snippet": re.sub(r"<[^>]+>", "", snippet_html).strip(),
        })
    return results or [{"info": "No results."}]


# ──────────────────────────────────────────────────────────────
# TOOLS
# ──────────────────────────────────────────────────────────────

# ── 1. Web search ─────────────────────────────────────────────

@tool
def web_search(query: str) -> str:
    """
    Search the internet for any information relevant to The Organic World
    Hyderabad — reviews, competitor news, pricing, expansions, sentiment, etc.

    Args:
        query: A specific search query. The agent will automatically
               add Hyderabad/TOW context when relevant, so keep the
               query focused (e.g. "Naturally Yours Hyderabad prices",
               "24 Mantra organic store customer reviews Hyderabad",
               "organic grocery delivery Hyderabad competitors 2025").

    Returns:
        JSON array of {title, url, snippet} dicts from DuckDuckGo.
    """
    results = _ddg(query, n=7)
    return json.dumps(results, indent=2, ensure_ascii=False)


# ── 2. Review tools ───────────────────────────────────────────

@tool
def save_review(
    store_location: str,
    product_name: str,
    reviewer_name: str,
    rating: int,
    review_text: str,
    source: str = "manual",
) -> str:
    """
    Save a customer review for a TOW Hyderabad store to tow_reviews.csv.

    Args:
        store_location: TOW store area, e.g. "Pragathi Nagar", "Kokapet".
        product_name:   Product or category name.
        reviewer_name:  Reviewer name/alias. Use "Anonymous" if unknown.
        rating:         Integer 1–5.
        review_text:    Full review text.
        source:         Platform, e.g. "Justdial", "Google Maps", "manual".

    Returns:
        Confirmation with assigned review ID.
    """
    rating = int(rating)
    if not (1 <= rating <= 5):
        return "Error: rating must be 1–5."
    dedup_key = f"{store_location}|{review_text[:120]}"
    if check_and_mark("reviews", dedup_key):
        return f"⏭️  Skipped (duplicate review already stored for '{store_location}')."
    row = _append("reviews", {
        "store_location": store_location.strip(),
        "product_name":   product_name.strip() or "General",
        "reviewer_name":  reviewer_name.strip() or "Anonymous",
        "rating":         rating,
        "review_text":    review_text.strip(),
        "source":         source.strip(),
        "sentiment":      "positive" if rating >= 4 else ("neutral" if rating == 3 else "negative"),
    })
    return f"✅ Review #{row['id']} saved — {store_location} | {rating}★ | source: {source}"


@tool
def get_reviews(store_location: Optional[str] = None, min_rating: int = 1) -> str:
    """
    Retrieve TOW reviews from tow_reviews.csv, with optional filters.

    Args:
        store_location: (Optional) Partial store name filter.
        min_rating:     (Optional) Only return reviews >= this rating (default 1).

    Returns:
        JSON list of matching reviews.
    """
    rows = _read("reviews")
    if store_location:
        rows = [r for r in rows if store_location.lower() in r["store_location"].lower()]
    rows = [r for r in rows if int(r["rating"]) >= int(min_rating)]
    if not rows:
        return "No reviews found."
    return json.dumps(rows, indent=2, ensure_ascii=False)


@tool
def review_summary(store_location: str = "") -> str:
    """
    Generate a statistical review summary, optionally for a specific store.

    Args:
        store_location: Partial name filter. Leave empty for all stores.

    Returns:
        Plain-text summary with avg rating, distribution, best/worst.
    """
    rows = _read("reviews")
    if store_location:
        rows = [r for r in rows if store_location.lower() in r["store_location"].lower()]
    if not rows:
        return "No reviews to summarise."

    ratings = [int(r["rating"]) for r in rows]
    avg = sum(ratings) / len(ratings)
    dist = {str(i): ratings.count(i) for i in range(1, 6)}
    best  = max(rows, key=lambda r: int(r["rating"]))
    worst = min(rows, key=lambda r: int(r["rating"]))
    pos   = sum(1 for r in rows if r["sentiment"] == "positive")
    neg   = sum(1 for r in rows if r["sentiment"] == "negative")

    label = f"TOW {store_location}" if store_location else "ALL TOW Hyderabad Stores"
    lines = [
        f"📊 Review Summary — {label}",
        f"   Total     : {len(rows)}  |  Avg: {avg:.2f}/5",
        f"   Sentiment : ✅ {pos} positive  ❌ {neg} negative  ⚖️ {len(rows)-pos-neg} neutral",
        f"   Stars     : ⭐×{dist['1']} ⭐⭐×{dist['2']} ⭐⭐⭐×{dist['3']} ⭐⭐⭐⭐×{dist['4']} ⭐⭐⭐⭐⭐×{dist['5']}",
        "",
        f"   🏆 Best  (★{best['rating']}) [{best['product_name']}] — {best['review_text'][:160]}…",
        f"   👎 Worst (★{worst['rating']}) [{worst['product_name']}] — {worst['review_text'][:160]}…",
    ]
    return "\n".join(lines)


# ── 3. Competitor tools ───────────────────────────────────────

@tool
def save_competitor(
    competitor_name: str,
    location: str,
    category: str,
    strengths: str,
    weaknesses: str,
    price_positioning: str,
    notable_products: str,
    online_presence: str,
    source: str,
) -> str:
    """
    Save a competitor profile to tow_competitors.csv.

    Args:
        competitor_name:   Name of the competitor store/brand.
        location:          Location in Hyderabad (area or full address).
        category:          Type: "organic_retail", "online_organic", "supermarket", etc.
        strengths:         Comma-separated strengths vs TOW.
        weaknesses:        Comma-separated weaknesses vs TOW.
        price_positioning: "premium", "similar", or "budget" relative to TOW.
        notable_products:  Key products or unique offerings.
        online_presence:   Website / app / delivery platform presence.
        source:            Where this data was gathered from.

    Returns:
        Confirmation with assigned ID.
    """
    row = _append("competitors", {
        "competitor_name":  competitor_name.strip(),
        "location":         location.strip(),
        "category":         category.strip(),
        "strengths":        strengths.strip(),
        "weaknesses":       weaknesses.strip(),
        "price_positioning": price_positioning.strip(),
        "notable_products": notable_products.strip(),
        "online_presence":  online_presence.strip(),
        "source":           source.strip(),
    })
    return f"✅ Competitor #{row['id']} saved — {competitor_name}"


@tool
def get_competitors(category: Optional[str] = None) -> str:
    """
    Retrieve all stored competitor profiles.

    Args:
        category: (Optional) Filter by category, e.g. "organic_retail".

    Returns:
        JSON list of competitor records.
    """
    rows = _read("competitors")
    if category:
        rows = [r for r in rows if category.lower() in r["category"].lower()]
    if not rows:
        return "No competitor data yet."
    return json.dumps(rows, indent=2, ensure_ascii=False)


@tool
def competitor_comparison() -> str:
    """
    Generate a side-by-side competitive comparison table of all stored
    competitors against The Organic World.

    Returns:
        Plain-text competitive landscape summary.
    """
    rows = _read("competitors")
    if not rows:
        return "No competitors in database. Run save_competitor or search first."

    lines = [
        "🏪 Competitive Landscape — The Organic World Hyderabad",
        "=" * 60,
    ]
    for r in rows:
        lines += [
            f"\n📌 {r['competitor_name']}  [{r['category']}]",
            f"   Location  : {r['location']}",
            f"   Pricing   : {r['price_positioning']} vs TOW",
            f"   Strengths : {r['strengths']}",
            f"   Weaknesses: {r['weaknesses']}",
            f"   Products  : {r['notable_products']}",
            f"   Online    : {r['online_presence']}",
        ]
    return "\n".join(lines)


# ── 4. News / market intelligence ─────────────────────────────

@tool
def save_news(
    headline: str,
    summary: str,
    url: str,
    source: str,
    relevance_tag: str,
) -> str:
    """
    Save a news item or market intelligence piece to tow_news.csv.

    Args:
        headline:      Short headline.
        summary:       2–4 sentence summary of the article/news.
        url:           Source URL.
        source:        Publication name.
        relevance_tag: One of: "TOW", "competitor", "market_trend",
                       "regulation", "consumer_sentiment".

    Returns:
        Confirmation with assigned ID.
    """
    if check_and_mark("news", headline + summary[:80]):
        return f"⏭️  Skipped (duplicate news already stored: '{headline[:60]}')."
    row = _append("news", {
        "summary":      summary.strip(),
        "url":          url.strip(),
        "source":       source.strip(),
        "relevance_tag": relevance_tag.strip(),
    })
    return f"✅ News #{row['id']} saved — {headline[:60]}"


@tool
def get_news(relevance_tag: Optional[str] = None) -> str:
    """
    Retrieve stored news items, optionally filtered by relevance tag.

    Args:
        relevance_tag: (Optional) Filter by tag: "TOW", "competitor",
                       "market_trend", "regulation", "consumer_sentiment".

    Returns:
        JSON list of news records.
    """
    rows = _read("news")
    if relevance_tag:
        rows = [r for r in rows if r["relevance_tag"].lower() == relevance_tag.lower()]
    if not rows:
        return "No news items found."
    return json.dumps(rows, indent=2, ensure_ascii=False)


# ── 5. Pricing intelligence ────────────────────────────────────

@tool
def save_price_comparison(
    product_name: str,
    tow_price: float,
    competitor_name: str,
    competitor_price: float,
    notes: str,
    source: str,
) -> str:
    """
    Save a product price comparison between TOW and a competitor.

    Args:
        product_name:     Product being compared (e.g. "Organic Turmeric 100g").
        tow_price:        TOW's price in INR.
        competitor_name:  Competitor name.
        competitor_price: Competitor's price in INR.
        notes:            Any relevant context (pack size, quality differences).
        source:           Where prices were found.

    Returns:
        Confirmation with price delta percentage.
    """
    tow_price = float(tow_price)
    competitor_price = float(competitor_price)
    diff_pct = round(((competitor_price - tow_price) / tow_price) * 100, 1) if tow_price else 0
    row = _append("pricing", {
        "product_name":     product_name.strip(),
        "tow_price":        tow_price,
        "competitor_name":  competitor_name.strip(),
        "competitor_price": competitor_price,
        "price_diff_pct":   diff_pct,
        "notes":            notes.strip(),
        "source":           source.strip(),
    })
    direction = "cheaper" if diff_pct < 0 else "more expensive"
    return (
        f"✅ Price saved #{row['id']} — {product_name}: "
        f"TOW ₹{tow_price} vs {competitor_name} ₹{competitor_price} "
        f"({abs(diff_pct)}% {direction} at competitor)"
    )


@tool
def get_pricing_report() -> str:
    """
    Generate a pricing intelligence report from stored price comparisons.

    Returns:
        Summary of TOW's price positioning vs each competitor.
    """
    rows = _read("pricing")
    if not rows:
        return "No pricing data yet."

    lines = ["💰 Pricing Intelligence Report — TOW vs Competitors", "=" * 55]
    by_comp: dict[str, list[dict]] = {}
    for r in rows:
        by_comp.setdefault(r["competitor_name"], []).append(r)

    for comp, items in sorted(by_comp.items()):
        diffs = [float(r["price_diff_pct"]) for r in items]
        avg_diff = sum(diffs) / len(diffs)
        direction = "cheaper" if avg_diff < 0 else "pricier"
        lines.append(
            f"\n📌 vs {comp}  ({len(items)} products compared)\n"
            f"   Avg competitor price is {abs(avg_diff):.1f}% {direction} than TOW\n"
            f"   Products: " + ", ".join(r["product_name"] for r in items[:5])
        )
    return "\n".join(lines)


# ── 6. Strategic intel ─────────────────────────────────────────

@tool
def save_intel(
    intel_type: str,
    subject: str,
    detail: str,
    strategic_implication: str,
    source: str,
) -> str:
    """
    Save a strategic intelligence item (SWOT signal, opportunity, threat, trend).

    Args:
        intel_type:             One of: "strength", "weakness", "opportunity",
                                "threat", "trend", "customer_pain_point".
        subject:                Brief subject label (e.g. "Delivery Speed",
                                "24 Mantra ITC Acquisition", "Millet trend").
        detail:                 Full detail of the intelligence item.
        strategic_implication:  What this means for TOW Hyderabad strategy.
        source:                 Data source (URL, publication, or "analysis").

    Returns:
        Confirmation with ID.
    """
    valid = {"strength", "weakness", "opportunity", "threat", "trend", "customer_pain_point"}
    if intel_type not in valid:
        return f"Error: intel_type must be one of {sorted(valid)}."
    if check_and_mark("intel", subject + detail[:80]):
        return f"⏭️  Skipped (duplicate intel already stored: '{subject[:60]}')."
    row = _append("intel", {
        "intel_type":            intel_type,
        "subject":               subject.strip(),
        "detail":                detail.strip(),
        "strategic_implication": strategic_implication.strip(),
        "source":                source.strip(),
    })
    return f"✅ Intel #{row['id']} saved [{intel_type.upper()}] — {subject}"


@tool
def generate_swot() -> str:
    """
    Generate a full SWOT analysis for The Organic World Hyderabad
    from all saved intelligence items plus embedded market knowledge.

    Returns:
        Structured SWOT report.
    """
    rows = _read("intel")
    grouped: dict[str, list[str]] = {
        "strength": [], "weakness": [], "opportunity": [],
        "threat": [], "trend": [], "customer_pain_point": [],
    }
    for r in rows:
        t = r["intel_type"]
        if t in grouped:
            grouped[t].append(f"  • {r['subject']}: {r['detail'][:120]}")

    lines = [
        "🔍 SWOT Analysis — The Organic World, Hyderabad",
        "=" * 55,
        "\n💪 STRENGTHS",
    ]
    lines += grouped["strength"] or ["  • (none recorded yet)"]
    lines += ["\n⚠️  WEAKNESSES"]
    lines += grouped["weakness"] or ["  • (none recorded yet)"]
    lines += ["\n🚀 OPPORTUNITIES"]
    lines += grouped["opportunity"] or ["  • (none recorded yet)"]
    lines += ["\n🔥 THREATS"]
    lines += grouped["threat"] or ["  • (none recorded yet)"]
    if grouped["trend"]:
        lines += ["\n📈 MARKET TRENDS"]
        lines += grouped["trend"]
    if grouped["customer_pain_point"]:
        lines += ["\n😤 CUSTOMER PAIN POINTS"]
        lines += grouped["customer_pain_point"]
    return "\n".join(lines)


@tool
def full_intel_report() -> str:
    """
    Generate a complete competitive intelligence briefing covering:
    reviews, competitors, news, pricing, and SWOT in one consolidated report.

    Returns:
        Full multi-section intelligence report as plain text.
    """
    sections = []

    # Reviews
    rev_rows = _read("reviews")
    if rev_rows:
        ratings = [int(r["rating"]) for r in rev_rows]
        avg = sum(ratings) / len(ratings)
        pos = sum(1 for r in rev_rows if r["sentiment"] == "positive")
        sections.append(
            f"━━ 1. CUSTOMER REVIEWS\n"
            f"   Total: {len(rev_rows)}  |  Avg: {avg:.2f}/5  |  "
            f"Positive: {pos}/{len(rev_rows)} ({100*pos//len(rev_rows)}%)"
        )
    else:
        sections.append("━━ 1. CUSTOMER REVIEWS\n   No reviews yet.")

    # Competitors
    comp_rows = _read("competitors")
    if comp_rows:
        names = ", ".join(r["competitor_name"] for r in comp_rows)
        sections.append(f"━━ 2. COMPETITORS TRACKED\n   {len(comp_rows)} tracked: {names}")
    else:
        sections.append("━━ 2. COMPETITORS TRACKED\n   None yet.")

    # News
    news_rows = _read("news")
    if news_rows:
        tags = {}
        for r in news_rows:
            tags[r["relevance_tag"]] = tags.get(r["relevance_tag"], 0) + 1
        sections.append(
            f"━━ 3. NEWS & MARKET INTEL\n"
            f"   {len(news_rows)} items — " + ", ".join(f"{k}:{v}" for k, v in tags.items())
        )
    else:
        sections.append("━━ 3. NEWS & MARKET INTEL\n   No items yet.")

    # Pricing
    price_rows = _read("pricing")
    if price_rows:
        sections.append(f"━━ 4. PRICING DATA\n   {len(price_rows)} product comparisons stored.")
    else:
        sections.append("━━ 4. PRICING DATA\n   No comparisons yet.")

    # SWOT
    intel_rows = _read("intel")
    if intel_rows:
        counts = {}
        for r in intel_rows:
            counts[r["intel_type"]] = counts.get(r["intel_type"], 0) + 1
        sections.append(
            "━━ 5. SWOT SIGNALS\n   "
            + "  ".join(f"{k.upper()}: {v}" for k, v in sorted(counts.items()))
        )
    else:
        sections.append("━━ 5. SWOT SIGNALS\n   None recorded yet.")

    header = (
        "╔══════════════════════════════════════════════════════════╗\n"
        "║  COMPETITIVE INTELLIGENCE BRIEF — The Organic World Hyd  ║\n"
        f"║  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}                              ║\n"
        "╚══════════════════════════════════════════════════════════╝"
    )
    return header + "\n\n" + "\n\n".join(sections)


# ──────────────────────────────────────────────────────────────
# ReAct Prompt
# ──────────────────────────────────────────────────────────────

REACT_PROMPT = PromptTemplate.from_template(
    """You are a Senior Competitive Intelligence Analyst for
The Organic World (TOW) — an organic grocery retail chain expanding
aggressively in Hyderabad, India.

Your goal is to build a comprehensive, always-updated intelligence
picture of TOW's position in the Hyderabad organic retail market.

== KNOWN CONTEXT (use this to enrich analysis) ==
TOW Hyderabad stores: Pragathi Nagar (4.9★), Hafeezpet (5.0★),
  Kokapet/Narsingi (4.7★), Jeedimetla/Bashirabad (5.0★),
  Nallagandla/Serilingampally (5.0★). Target: 30 stores by end 2025.
  Parent: Nimida Group (Bengaluru). Founded 2017. 3,000+ SKUs.
  Bans 25 harmful chemicals. Revenue target: ₹100 Cr by FY2025.

Key competitors in Hyderabad:
  - 24 Mantra Organic (Sresta, HQ Madhapur, founded 2004, now ITC-owned,
    ₹278 Cr revenue, 1500+ outlets, strong brand equity)
  - Naturally Yours (founded 2010, premium organic, express delivery,
    specialty range: GF grains, organic pasta)
  - Lahaan Organics (founded 2017, farm-to-table traceability, organic
    rice, pulses, oils)
  - Pure and Sure / Phalada Agro (150+ certified products, own store
    at Banjara Hills, eco-conscious supply chain)
  - Gourmet Garden India (premium organic delivery, Hyderabad coverage)
  - Jiva Organics, Good Seeds, Bio India Biologicals (local HYD players)

Market context:
  - Indian organic market: $1.58B (2023) → $8.9B by 2032 (21% CAGR)
  - Health food segment: ₹63,093 Cr, growing 11.7% CAGR (Kantar 2024)
  - ITC acquired 24 Mantra/Sresta in April 2025 for ₹472 Cr
  - Tata acquired Organic India in Jan 2024 for ₹1,900 Cr
  - Quick commerce is a growing channel for organic delivery

== YOUR TOOLS ==
{tools}

Tool names: {tool_names}

== AUTOMATION CONTEXT ==
This agent runs BOTH interactively (cli.py) AND automatically via
scheduler.py which triggers daily collection jobs. When you receive
a scheduled job instruction, be efficient: search → extract → save.
Duplicate saves are automatically rejected with a "⏭️ Skipped" message —
this is normal. Do NOT retry skipped items.

== RULES ==
1. ALWAYS use web_search before saving — NEVER fabricate data.
2. After searching, extract actionable insights and save using the
   right tool: save_review, save_competitor, save_news,
   save_price_comparison, or save_intel.
3. For competitor research, ALWAYS also call save_intel with the
   strategic implication for TOW.
4. "⏭️ Skipped" responses from save tools mean the data is already
   stored — treat as success, do NOT retry.
5. When asked for a report or analysis, call full_intel_report or
   generate_swot to produce structured output.
6. Use valid JSON for ALL Action Inputs.
7. Intel types: strength / weakness / opportunity / threat / trend /
   customer_pain_point.
8. For automated jobs: search 1-2 queries, save what's new, done.

Use EXACTLY this format:

Question: the user's input
Thought: reason step by step
Action: one of [{tool_names}]
Action Input: valid JSON
Observation: the result
... (repeat as needed)
Thought: I have enough to answer
Final Answer: your response to the user

Begin!

Question: {input}
Thought:{agent_scratchpad}"""
)

# ──────────────────────────────────────────────────────────────
# All tools list
# ──────────────────────────────────────────────────────────────

TOOLS = [
    web_search,
    save_review,       get_reviews,       review_summary,
    save_competitor,   get_competitors,   competitor_comparison,
    save_news,         get_news,
    save_price_comparison, get_pricing_report,
    save_intel,        generate_swot,
    full_intel_report,
]


# ──────────────────────────────────────────────────────────────
# Agent factory
# ──────────────────────────────────────────────────────────────

def build_agent(
    model: str = "qwen2.5",
    base_url: str = "http://localhost:11434",
) -> AgentExecutor:
    """
    Build the competitive intelligence AgentExecutor.

    Args:
        model:    Ollama model (must be pulled: `ollama pull qwen2.5`).
        base_url: Ollama server URL.

    Returns:
        Ready-to-invoke AgentExecutor.
    """
    llm = ChatOllama(
        model=model,
        base_url=base_url,
        temperature=0.0,
        num_predict=2048,
    )
    agent = create_react_agent(llm=llm, tools=TOOLS, prompt=REACT_PROMPT)
    return AgentExecutor(
        agent=agent,
        tools=TOOLS,
        verbose=True,
        max_iterations=15,
        handle_parsing_errors=True,
        return_intermediate_steps=False,
    )