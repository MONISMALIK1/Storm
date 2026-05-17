"""
Interactive CLI for the TOW Competitive Intelligence Agent.

Usage:
    # Single query
    python -m intel.agent.cli --task "What are the top competitor threats this week?"

    # Daily brief
    python -m intel.agent.cli --brief

    # Run alert scan
    python -m intel.agent.cli --alerts

    # Pull fresh data then brief
    python -m intel.agent.cli --ingest --brief

    # Interactive REPL
    python -m intel.agent.cli

    # Show graph topology
    python -m intel.agent.cli --diagram
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any


def _print_usage_summary(metadata: dict) -> None:
    usage = metadata.get("usage", {})
    if not usage:
        return
    total_in = usage.get("input_tokens", 0)
    total_out = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_write = usage.get("cache_creation_input_tokens", 0)

    # Cost estimates (Opus 4.7: $5/M input, $25/M output; cache read ~0.1x, write 1.25x)
    cost_in = (total_in - cache_read) * 5 / 1_000_000
    cost_out = total_out * 25 / 1_000_000
    cost_cache_read = cache_read * 0.5 / 1_000_000    # ~0.1x
    cost_cache_write = cache_write * 6.25 / 1_000_000  # 1.25x

    total_cost = cost_in + cost_out + cost_cache_read + cost_cache_write
    cache_pct = round(cache_read / total_in * 100) if total_in > 0 else 0

    print(f"\n{'─'*60}")
    print("📈 Token Usage Summary")
    print(f"   Input tokens:        {total_in:>8,}  (cache read: {cache_read:,}, {cache_pct}%)")
    print(f"   Output tokens:       {total_out:>8,}")
    print(f"   Cache write tokens:  {cache_write:>8,}")
    print(f"   Estimated cost:      ${total_cost:.4f}")
    print(f"{'─'*60}\n")


def _print_recommendations(recommendations: list[str]) -> None:
    if not recommendations:
        return
    print("\n🎯 Strategic Recommendations")
    print("─" * 60)
    for i, rec in enumerate(recommendations, 1):
        print(f"{i}. {rec}\n")


def _print_alerts(alerts: list[dict]) -> None:
    if not alerts:
        print("✅ No open alerts.")
        return

    priority_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}
    critical_high = [a for a in alerts if a.get("priority") in ("CRITICAL", "HIGH")]
    rest = [a for a in alerts if a.get("priority") not in ("CRITICAL", "HIGH")]

    print(f"\n🚨 Open Alerts ({len(alerts)} total)")
    print("─" * 60)
    for alert in critical_high + rest:
        pri = alert.get("priority", "?")
        emoji = priority_emoji.get(pri, "⚪")
        print(f"{emoji} [{pri}] {alert.get('subject', '')}")
        if alert.get("detail"):
            print(f"   {alert['detail'][:120]}")
        print()


def _make_initial_state(task_input: str) -> dict:
    return {
        "task_input": task_input,
        "task_type": "",
        "collected_data": {},
        "analysis": {},
        "alerts": [],
        "briefing": "",
        "recommendations": [],
        "metadata": {},
        "messages": [],
    }


def run_task(task_input: str, *, verbose: bool = False) -> dict:
    """Run the CI agent for a single task and return the final state."""
    from intel.agent.graph import build_graph
    from intel.db import init_db

    # Ensure DB is initialized
    try:
        init_db()
    except Exception:
        pass

    graph = build_graph(use_persistence=False)
    state = _make_initial_state(task_input)

    t0 = time.monotonic()
    print(f"\n🤖 TOW CI Agent — Processing: {task_input[:80]}")
    print("─" * 60)

    result = graph.invoke(state)

    elapsed = time.monotonic() - t0
    result.setdefault("metadata", {})["total_elapsed_s"] = round(elapsed, 2)

    if verbose:
        node_times = {
            k: v.get("elapsed_s")
            for k, v in result.get("metadata", {}).items()
            if isinstance(v, dict) and "elapsed_s" in v
        }
        print(f"\n⏱  Node timing: {node_times}")
        print(f"   Total: {elapsed:.1f}s")

    return result


def interactive_repl() -> None:
    """Start an interactive REPL session with persistent graph state."""
    from intel.agent.graph import build_graph
    from intel.db import init_db

    try:
        init_db()
    except Exception:
        pass

    graph = build_graph(use_persistence=True)
    config = {"configurable": {"thread_id": "repl-session"}}

    print("\n" + "═" * 60)
    print("  TOW Competitive Intelligence Agent — Interactive Mode")
    print("  Type 'help' for commands | 'quit' to exit")
    print("═" * 60 + "\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("👋 Goodbye!")
            break

        if user_input.lower() == "help":
            print("""
Commands:
  daily brief     — Generate today's executive briefing
  scan alerts     — Run alert detection and show open alerts
  ingest          — Pull fresh data from scrapers
  competitor X    — Ask about a specific competitor
  pricing X       — Ask about pricing for a product
  quit / exit     — Exit the REPL
  Any other text  — Treated as a free-form intelligence query
""")
            continue

        state = _make_initial_state(user_input)
        t0 = time.monotonic()

        try:
            result = graph.invoke(state, config=config)
        except Exception as e:
            print(f"\n❌ Error: {e}")
            continue

        # Show alerts if present
        if result.get("alerts"):
            _print_alerts(result["alerts"])

        # Briefing was already streamed; show recommendations if any
        if result.get("recommendations"):
            _print_recommendations(result["recommendations"])

        _print_usage_summary(result.get("metadata", {}))
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="intel.agent.cli",
        description="TOW Competitive Intelligence Agent",
    )
    parser.add_argument("--task", "-t", help="Run a single intelligence query")
    parser.add_argument("--brief", "-b", action="store_true", help="Generate daily executive brief")
    parser.add_argument("--alerts", "-a", action="store_true", help="Run alert scan")
    parser.add_argument("--ingest", "-i", action="store_true", help="Pull fresh data from scrapers")
    parser.add_argument("--strategy", "-s", action="store_true", help="Generate strategic recommendations")
    parser.add_argument("--diagram", action="store_true", help="Print graph topology and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show timing and token details")

    args = parser.parse_args(argv)

    # Load .env if present
    env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
    if os.path.exists(env_path):
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            pass

    if args.diagram:
        from intel.agent.graph import print_graph_diagram
        print_graph_diagram()
        return 0

    if args.ingest and args.brief:
        task = "Ingest fresh data from all scrapers, then generate the daily executive brief."
    elif args.ingest:
        task = "Pull fresh data from all scrapers (run_ingest) and report the results."
    elif args.brief:
        task = "Generate the daily executive brief with full competitive intelligence."
    elif args.alerts:
        task = "Run the alert detection scan and show me all open alerts by priority."
    elif args.strategy:
        task = "Perform a comprehensive strategic analysis and give me top 5 recommendations."
    elif args.task:
        task = args.task
    else:
        # No flags — drop into interactive mode
        interactive_repl()
        return 0

    result = run_task(task, verbose=args.verbose)

    # If briefing wasn't streamed (non-brief tasks), print it
    briefing = result.get("briefing", "")
    if briefing and not args.brief and not args.alerts:
        print("\n" + briefing)

    if result.get("recommendations"):
        _print_recommendations(result["recommendations"])

    if result.get("alerts") and args.alerts:
        _print_alerts(result["alerts"])

    if args.verbose:
        _print_usage_summary(result.get("metadata", {}))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
