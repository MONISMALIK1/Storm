"""
cli.py — Interactive CLI for the TOW Competitive Intelligence Agent
"""

import argparse
import sys
from agent import build_agent

BANNER = """
╔══════════════════════════════════════════════════════════════════════╗
║  🌿  The Organic World Hyderabad — Competitive Intelligence Agent    ║
║      LangChain  ×  Ollama  ×  Web Search  ×  Daily Automation       ║
╠══════════════════════════════════════════════════════════════════════╣
║  INTERACTIVE QUERIES                                                 ║
║   "Give me the full competitive intelligence brief"                  ║
║   "Generate a SWOT analysis for TOW Hyderabad"                       ║
║   "Search for 24 Mantra news and save it"                            ║
║   "What threats should TOW Hyderabad worry about?"                   ║
║   "Show pricing intelligence report"                                 ║
║   Type 'digest' or 'alerts' for quick reports                        ║
║                                                                      ║
║  SCHEDULER (run in terminal separately)                              ║
║   python scheduler.py              → run all daily jobs now          ║
║   python scheduler.py --daemon     → auto-run every day at 7 AM     ║
║   python scheduler.py --digest     → print today's digest           ║
║   python scheduler.py --list-jobs  → see all collection jobs         ║
╚══════════════════════════════════════════════════════════════════════╝
"""


def show_startup_alerts():
    try:
        from change_detector import get_unacknowledged
        alerts = get_unacknowledged(since_hours=48)
        if alerts:
            icons = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
            print(f"\n  ⚠️  {len(alerts)} unacknowledged alert(s):")
            for a in alerts[:4]:
                print(f"  {icons.get(a['priority'],'•')} [{a['priority']}] {a['subject']}")
            if len(alerts) > 4:
                print(f"  ... +{len(alerts)-4} more. Run: python scheduler.py --digest")
            print()
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="TOW CI Agent CLI")
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--url", default="http://localhost:11434")
    args = parser.parse_args()

    print(BANNER)
    show_startup_alerts()
    print(f"  🔌 Connecting → Ollama @ {args.url}  |  model: {args.model}\n")

    try:
        executor = build_agent(model=args.model, base_url=args.url)
        print("  ✅ Agent ready.\n")
    except Exception as exc:
        print(f"  ❌ Could not start agent: {exc}")
        sys.exit(1)

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Bye! 👋")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "bye", "q"}:
            print("  Goodbye! 👋")
            break

        if user_input.lower() == "digest":
            try:
                from scheduler import build_digest
                print(build_digest())
            except Exception as exc:
                print(f"  Error: {exc}")
            continue

        if user_input.lower() == "alerts":
            try:
                from change_detector import get_unacknowledged, format_alerts
                print(format_alerts(get_unacknowledged(since_hours=48)))
            except Exception as exc:
                print(f"  Error: {exc}")
            continue

        try:
            result = executor.invoke({"input": user_input})
            print(f"\nAgent: {result['output']}\n")
        except Exception as exc:
            print(f"\n  ⚠️  Error: {exc}\n")


if __name__ == "__main__":
    main()