"""
LangGraph node functions for the CI Agent.

Each node:
  1. Receives the full CIAgentState
  2. Builds a targeted prompt using the cached system block
  3. Calls Claude (with or without tools) via client.run_agent_turn()
  4. Returns a partial state dict (LangGraph merges automatically)

Node registry:
  supervisor          → classifies the task_type
  data_collector      → queries intel DB with all relevant tools
  analyzer            → derives patterns, anomalies, themes from collected_data
  alert_checker       → fetches + triggers alerts
  briefing_generator  → writes the executive briefing (streaming)
  strategist          → generates prioritised strategic recommendations
"""
from __future__ import annotations

import json
import time
from typing import Any

from .client import run_agent_turn, stream_agent_turn
from .prompts import get_cached_system_block
from .state import CIAgentState
from .tools import TOOL_DEFINITIONS


# ── Helpers ────────────────────────────────────────────────────────────────────

def _merge_usage(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}


def _system() -> list[dict]:
    return get_cached_system_block()


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _json_snippet(data: Any, max_chars: int = 6000) -> str:
    raw = json.dumps(data, default=str, ensure_ascii=False, indent=2)
    if len(raw) > max_chars:
        raw = raw[:max_chars] + "\n... (truncated)"
    return raw


# ── 1. Supervisor node ─────────────────────────────────────────────────────────

def supervisor_node(state: CIAgentState) -> dict:
    """
    Classify the user's request into one of the known task types and decide
    which downstream nodes to activate. Does NOT call any tools.
    """
    task_input = state.get("task_input", "")
    t0 = time.monotonic()

    messages = [
        _user(
            f"""Classify this request into exactly ONE task type from the list below.
Respond with ONLY the task_type string — no explanation.

Task types:
  daily_brief        — user wants a full daily / weekly executive briefing
  alert_scan         — user wants to see or trigger alerts
  competitor_query   — question about a specific competitor or competitive landscape
  pricing_query      — question about prices, price gaps, or price threats
  review_query       — question about customer reviews or ratings
  news_query         — question about market or competitor news
  strategy           — request for strategic analysis or recommendations
  ingest             — user wants to pull fresh data from scrapers
  unknown            — none of the above

User request: {task_input}"""
        )
    ]

    text, updated_msgs, usage = run_agent_turn(
        system=_system(),
        messages=messages,
        tools=[],   # no tools for classification
        max_tokens=64,
        effort="low",
    )

    task_type = text.strip().lower().split()[0] if text.strip() else "unknown"
    valid_types = {
        "daily_brief", "alert_scan", "competitor_query", "pricing_query",
        "review_query", "news_query", "strategy", "ingest", "unknown",
    }
    if task_type not in valid_types:
        task_type = "unknown"

    elapsed = time.monotonic() - t0
    meta = dict(state.get("metadata", {}))
    meta["supervisor"] = {"task_type": task_type, "elapsed_s": round(elapsed, 2)}
    meta["usage"] = _merge_usage(meta.get("usage", {}), usage)

    return {
        "task_type": task_type,
        "messages": updated_msgs,
        "metadata": meta,
    }


# ── 2. Data collector node ─────────────────────────────────────────────────────

def data_collector_node(state: CIAgentState) -> dict:
    """
    Query all relevant intel sources based on task_type.
    Uses the full tool set; Claude decides which tools to call and how many times.
    """
    task_type = state.get("task_type", "unknown")
    task_input = state.get("task_input", "")
    t0 = time.monotonic()

    # Tailor the prompt to the task so Claude picks the right tools
    if task_type == "daily_brief":
        directive = (
            "Collect a comprehensive data snapshot for a daily executive brief. "
            "You must call: get_dashboard_summary, get_unacked_alerts (hours=168), "
            "analyze_sentiment_trend, query_news (days=1), query_pricing (min_diff_pct=10), "
            "and query_intel (intel_type='threat', days=7). "
            "Summarise findings as structured JSON in your final response."
        )
    elif task_type == "strategy":
        directive = (
            "Collect all signals needed for a strategic review: dashboard summary, "
            "all competitors, pricing threats, recent intel (all types), news (days=14), "
            "and sentiment trend. Return structured findings."
        )
    elif task_type == "competitor_query":
        directive = (
            f"Answer this question about competitors by querying the right tools: "
            f"'{task_input}'. Use query_competitors and query_news as needed."
        )
    elif task_type == "pricing_query":
        directive = (
            f"Answer this pricing question: '{task_input}'. "
            "Use query_pricing and include context from query_competitors if relevant."
        )
    elif task_type == "review_query":
        directive = (
            f"Answer this question about reviews: '{task_input}'. "
            "Use query_reviews and analyze_sentiment_trend as needed."
        )
    elif task_type == "news_query":
        directive = (
            f"Answer this news question: '{task_input}'. "
            "Use query_news (expand days if needed) and cross-reference with query_intel."
        )
    else:
        directive = (
            f"Collect the data needed to answer: '{task_input}'. "
            "Call whichever tools are most relevant."
        )

    messages = [_user(directive)]
    text, updated_msgs, usage = run_agent_turn(
        system=_system(),
        messages=messages,
        tools=TOOL_DEFINITIONS,
        max_tokens=6000,
        effort="high",
    )

    # Parse Claude's structured summary if it returned JSON; else store raw text
    collected: dict = {}
    try:
        # Claude sometimes wraps JSON in ```json fences
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        collected = json.loads(raw)
    except Exception:
        collected = {"raw_summary": text}

    elapsed = time.monotonic() - t0
    meta = dict(state.get("metadata", {}))
    meta["data_collector"] = {"elapsed_s": round(elapsed, 2)}
    meta["usage"] = _merge_usage(meta.get("usage", {}), usage)

    return {
        "collected_data": collected,
        "messages": updated_msgs,
        "metadata": meta,
    }


# ── 3. Analyzer node ───────────────────────────────────────────────────────────

def analyzer_node(state: CIAgentState) -> dict:
    """
    Derive higher-order insights from collected_data: anomalies, correlations,
    trend direction, competitive positioning. No tool calls — pure reasoning.
    """
    collected = state.get("collected_data", {})
    task_type = state.get("task_type", "")
    t0 = time.monotonic()

    prompt = f"""You are analysing TOW's competitive intelligence data.

Collected data:
{_json_snippet(collected)}

Perform a structured analysis covering:
1. ANOMALIES — any metrics that are outside expected ranges or have changed sharply
2. CORRELATIONS — any signals that reinforce each other (e.g. low rating + price threat on same product)
3. TREND ASSESSMENT — improving / stable / declining across key metrics
4. TOP RISKS — rank the 3 most important risks with estimated business impact
5. QUICK WINS — any easy actions that could improve metrics within 1 week

Task context: {task_type}

Return your analysis as structured JSON with keys:
  anomalies, correlations, trend_assessment, top_risks, quick_wins
"""

    messages = [_user(prompt)]
    text, updated_msgs, usage = run_agent_turn(
        system=_system(),
        messages=messages,
        tools=[],       # pure reasoning, no tools needed
        max_tokens=4096,
        effort="high",
    )

    analysis: dict = {}
    try:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        analysis = json.loads(raw)
    except Exception:
        analysis = {"raw_analysis": text}

    elapsed = time.monotonic() - t0
    meta = dict(state.get("metadata", {}))
    meta["analyzer"] = {"elapsed_s": round(elapsed, 2)}
    meta["usage"] = _merge_usage(meta.get("usage", {}), usage)

    return {
        "analysis": analysis,
        "messages": updated_msgs,
        "metadata": meta,
    }


# ── 4. Alert checker node ──────────────────────────────────────────────────────

def alert_checker_node(state: CIAgentState) -> dict:
    """
    Fetch current alerts and optionally trigger a fresh scan.
    Also adds alert context to messages for downstream nodes.
    """
    task_type = state.get("task_type", "")
    t0 = time.monotonic()

    # For alert_scan tasks also run detection; for briefs just fetch
    if task_type == "alert_scan":
        directive = (
            "First run run_alert_scan to detect any new alerts, "
            "then call get_unacked_alerts to fetch all unacknowledged alerts. "
            "Return the combined list as JSON."
        )
    else:
        directive = (
            "Call get_unacked_alerts (hours=168) to get all open alerts. "
            "Return as JSON."
        )

    messages = [_user(directive)]
    alert_tools = [
        t for t in TOOL_DEFINITIONS
        if t["name"] in ("run_alert_scan", "get_unacked_alerts")
    ]
    text, updated_msgs, usage = run_agent_turn(
        system=_system(),
        messages=messages,
        tools=alert_tools,
        max_tokens=3000,
        effort="medium",
    )

    alerts: list[dict] = []
    try:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        alerts = parsed.get("alerts", parsed) if isinstance(parsed, dict) else parsed
    except Exception:
        alerts = [{"raw": text}]

    elapsed = time.monotonic() - t0
    meta = dict(state.get("metadata", {}))
    meta["alert_checker"] = {
        "alert_count": len(alerts),
        "elapsed_s": round(elapsed, 2),
    }
    meta["usage"] = _merge_usage(meta.get("usage", {}), usage)

    return {
        "alerts": alerts,
        "messages": updated_msgs,
        "metadata": meta,
    }


# ── 5. Briefing generator node (streaming) ────────────────────────────────────

def briefing_generator_node(state: CIAgentState) -> dict:
    """
    Generate the executive briefing by synthesising collected_data, analysis,
    and alerts. Uses streaming so the CLI can display progress in real time.
    """
    from datetime import date

    collected = state.get("collected_data", {})
    analysis = state.get("analysis", {})
    alerts = state.get("alerts", [])
    task_type = state.get("task_type", "")
    task_input = state.get("task_input", "")
    t0 = time.monotonic()

    today = date.today().strftime("%d %b %Y")

    prompt = f"""Generate a professional executive briefing for TOW leadership.

TODAY: {today}
TASK: {task_input}

=== DASHBOARD DATA ===
{_json_snippet(collected, 3000)}

=== ANALYSIS INSIGHTS ===
{_json_snippet(analysis, 2000)}

=== OPEN ALERTS ===
{_json_snippet(alerts, 2000)}

Write the briefing in the standard format:
## TOW Intelligence Brief — {today}
### At a Glance
### Alert Summary
### Competitor Watch
### Customer Sentiment
### Price Signals
### Key Findings
### Recommended Actions (3-5 bullets)

Be specific: use actual numbers, competitor names, store locations.
Flag CRITICAL/HIGH alerts prominently.
Keep total length under 600 words unless the situation warrants more.
"""

    messages = [_user(prompt)]
    briefing_parts: list[str] = []

    print("\n📊 Generating executive briefing...\n")
    print("─" * 60)

    with stream_agent_turn(
        system=_system(),
        messages=messages,
        tools=None,
        max_tokens=16_384,
        effort="high",
    ) as stream:
        for chunk in stream.text_stream:
            print(chunk, end="", flush=True)
            briefing_parts.append(chunk)
        final_msg = stream.get_final_message()

    print("\n" + "─" * 60 + "\n")

    briefing = "".join(briefing_parts)
    u = final_msg.usage
    usage = {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }

    elapsed = time.monotonic() - t0
    meta = dict(state.get("metadata", {}))
    meta["briefing_generator"] = {"elapsed_s": round(elapsed, 2)}
    meta["usage"] = _merge_usage(meta.get("usage", {}), usage)

    return {
        "briefing": briefing,
        "messages": messages + [{"role": "assistant", "content": briefing}],
        "metadata": meta,
    }


# ── 6. Strategist node ────────────────────────────────────────────────────────

def strategist_node(state: CIAgentState) -> dict:
    """
    Generate prioritised strategic recommendations based on all prior analysis.
    Returns a structured list of action items with owner, urgency, and rationale.
    """
    analysis = state.get("analysis", {})
    alerts = state.get("alerts", [])
    collected = state.get("collected_data", {})
    t0 = time.monotonic()

    prompt = f"""Based on TOW's competitive intelligence, generate 5 prioritised strategic recommendations.

Analysis:
{_json_snippet(analysis, 2000)}

Open Alerts:
{_json_snippet(alerts, 1500)}

Additional Context:
{_json_snippet(collected, 1500)}

For each recommendation provide:
  - action: imperative sentence describing what to do
  - rationale: why this matters (cite specific data)
  - owner: which role/team should act (Store Manager / Marketing / Ops / Pricing Team / CEO)
  - urgency: IMMEDIATE (today) / SHORT_TERM (this week) / MEDIUM_TERM (this month)
  - expected_outcome: measurable result if this is done

Return ONLY valid JSON:
{{
  "recommendations": [
    {{
      "priority": 1,
      "action": "...",
      "rationale": "...",
      "owner": "...",
      "urgency": "...",
      "expected_outcome": "..."
    }}
  ]
}}
"""

    messages = [_user(prompt)]
    text, updated_msgs, usage = run_agent_turn(
        system=_system(),
        messages=messages,
        tools=[],
        max_tokens=4096,
        effort="high",
    )

    recommendations: list[str] = []
    try:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        recs = parsed.get("recommendations", [])
        recommendations = [
            f"[{r.get('urgency', '')}] ({r.get('owner', '')}) "
            f"{r.get('action', '')} — {r.get('rationale', '')}"
            for r in recs
        ]
    except Exception:
        recommendations = [text]

    elapsed = time.monotonic() - t0
    meta = dict(state.get("metadata", {}))
    meta["strategist"] = {"elapsed_s": round(elapsed, 2)}
    meta["usage"] = _merge_usage(meta.get("usage", {}), usage)

    return {
        "recommendations": recommendations,
        "messages": updated_msgs,
        "metadata": meta,
    }
