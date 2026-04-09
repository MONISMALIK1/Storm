"""
scheduler.py — Daily Intelligence Collection Scheduler
=======================================================
The brain of the automation system. Runs all daily jobs,
feeds search results to the LangChain agent, deduplicates,
detects changes, and generates a daily digest report.

Usage:
    python scheduler.py              # run all daily jobs now
    python scheduler.py --dry-run    # show what would run, don't execute
    python scheduler.py --job tow_reviews_pragathi  # run one specific job
    python scheduler.py --daemon     # run continuously on schedule (cron-like)
    python scheduler.py --digest     # print today's digest only
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

# ── Setup logging ─────────────────────────────────────────────
LOG_FILE = "scheduler.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scheduler")

# ── State file ────────────────────────────────────────────────
STATE_FILE = "scheduler_state.json"


def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_run": None, "job_history": {}, "total_runs": 0, "total_records_collected": 0}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _load_agent(model: str = "qwen2.5:7b", base_url: str = "http://localhost:11434"):
    """Lazy-import and build the agent."""
    from agent import build_agent
    return build_agent(model=model, base_url=base_url)


# ── Daily digest builder ──────────────────────────────────────

def build_digest() -> str:
    """Generate today's intelligence digest from all CSVs."""
    import csv as csv_mod
    from change_detector import get_unacknowledged, format_alerts

    today = datetime.now().strftime("%A, %d %B %Y")
    state = _load_state()

    lines = [
        "╔══════════════════════════════════════════════════════════════╗",
        "║  🌿  The Organic World Hyderabad — Daily Intelligence Digest  ║",
        f"║  {today:<60}║",
        "╚══════════════════════════════════════════════════════════════╝",
        "",
    ]

    # ── Alerts ────────────────────────────────────────────────
    alerts = get_unacknowledged(since_hours=25)
    lines.append(f"🚨 ALERTS ({len(alerts)} new in last 24h)")
    lines.append("-" * 50)
    if alerts:
        for a in alerts[:5]:
            icon = {"CRITICAL":"🚨","HIGH":"🔴","MEDIUM":"🟡","LOW":"🟢"}.get(a["priority"],"•")
            lines.append(f"  {icon} [{a['priority']}] {a['subject']}")
            lines.append(f"     {a['detail'][:150]}")
    else:
        lines.append("  ✅ No alerts. All clear.")
    lines.append("")

    # ── Per-database stats ────────────────────────────────────
    db_files = {
        "📝 Reviews":     "tow_reviews.csv",
        "🏪 Competitors": "tow_competitors.csv",
        "📰 News":        "tow_news.csv",
        "💰 Pricing":     "tow_pricing.csv",
        "🔍 Intel":       "tow_intel.csv",
    }
    lines.append("📊 DATABASE STATUS")
    lines.append("-" * 50)
    today_str = datetime.now().strftime("%Y-%m-%d")
    for label, path in db_files.items():
        if not os.path.exists(path):
            lines.append(f"  {label}: 0 total (file not created)")
            continue
        with open(path, "r", encoding="utf-8") as f:
            rows = list(csv_mod.DictReader(f))
        total = len(rows)
        today_count = sum(1 for r in rows if r.get("timestamp","")[:10] == today_str)
        lines.append(f"  {label}: {total} total  |  +{today_count} today")
    lines.append("")

    # ── Today's top news ──────────────────────────────────────
    if os.path.exists("tow_news.csv"):
        with open("tow_news.csv", "r", encoding="utf-8") as f:
            news = list(csv_mod.DictReader(f))
        today_news = [n for n in news if n.get("timestamp","")[:10] == today_str]
        if today_news:
            lines.append(f"📰 TODAY'S INTELLIGENCE ({len(today_news)} items)")
            lines.append("-" * 50)
            for n in today_news[:6]:
                tag_icon = {"TOW":"🌿","competitor":"🏪","market_trend":"📈","regulation":"⚖️","consumer_sentiment":"💬"}.get(n.get("relevance_tag",""),"•")
                lines.append(f"  {tag_icon} {n.get('headline','')[:90]}")
                lines.append(f"     {n.get('summary','')[:150]}")
            lines.append("")

    # ── Today's reviews ───────────────────────────────────────
    if os.path.exists("tow_reviews.csv"):
        with open("tow_reviews.csv", "r", encoding="utf-8") as f:
            reviews = list(csv_mod.DictReader(f))
        today_rev = [r for r in reviews if r.get("timestamp","")[:10] == today_str]
        if today_rev:
            ratings = [int(r["rating"]) for r in today_rev if r.get("rating","").isdigit()]
            avg = sum(ratings)/len(ratings) if ratings else 0
            lines.append(f"⭐ TODAY'S REVIEWS ({len(today_rev)} new, avg {avg:.1f}/5)")
            lines.append("-" * 50)
            for r in today_rev[:4]:
                lines.append(f"  [{r.get('rating','?')}★] {r.get('store_location','?')[:40]} — {r.get('review_text','')[:100]}")
            lines.append("")

    # ── Scheduler stats ───────────────────────────────────────
    lines.append("⚙️  SCHEDULER STATUS")
    lines.append("-" * 50)
    lines.append(f"  Total runs  : {state.get('total_runs', 0)}")
    lines.append(f"  Total records: {state.get('total_records_collected', 0)}")
    lines.append(f"  Last run    : {state.get('last_run', 'Never')}")
    lines.append(f"  Log file    : {LOG_FILE}")

    return "\n".join(lines)


# ── Core job runner ───────────────────────────────────────────

def run_job(job: dict, executor, dry_run: bool = False) -> dict:
    """
    Execute one collection job using the agent.
    Returns a result dict with counts and status.
    """
    from dedup import check_and_mark
    from change_detector import run_detection

    job_id = job["job_id"]
    label = job["label"]
    queries = job["queries"]
    save_as = job.get("save_as", "news")

    log.info(f"▶  Running job: [{job_id}] {label}")

    if dry_run:
        log.info(f"   DRY RUN — would search: {queries[:2]}")
        return {"job_id": job_id, "status": "dry_run", "records": 0}

    records_saved = 0

    for query in queries:
        try:
            # Build a natural language instruction for the agent
            if save_as == "review":
                store = job.get("store_location", "Hyderabad")
                prompt = (
                    f"Search the internet for: '{query}'. "
                    f"Extract any customer reviews or ratings you find and save each one "
                    f"as a review for store location '{store}' using save_review. "
                    f"Skip anything already covered. Save up to 3 new reviews."
                )
            elif save_as == "intel":
                intel_type = job.get("intel_type", "trend")
                prompt = (
                    f"Search the internet for: '{query}'. "
                    f"Extract key intelligence insights. For each meaningful finding, "
                    f"save it using save_intel with intel_type='{intel_type}'. "
                    f"Include strategic implications for The Organic World Hyderabad."
                )
            else:  # news
                tag = job.get("relevance_tag", "market_trend")
                prompt = (
                    f"Search the internet for: '{query}'. "
                    f"Find any relevant news or information. Save each news item using "
                    f"save_news with relevance_tag='{tag}'. "
                    f"Write a 2-3 sentence summary. Save up to 3 new items."
                )

            result = executor.invoke({"input": prompt})
            output = result.get("output", "")
            log.info(f"   ✅ Query done: {query[:60]}...")

            # Count approximate saves from output
            saves = output.lower().count("saved") + output.lower().count("✅")
            records_saved += max(saves, 0)

            time.sleep(2)  # polite delay between searches

        except Exception as exc:
            log.warning(f"   ⚠️  Query failed [{query[:50]}]: {exc}")

    # Run change detection after each job
    new_alerts = run_detection()
    if new_alerts:
        log.info(f"   🚨 {len(new_alerts)} new alert(s) detected")

    return {
        "job_id": job_id,
        "status": "completed",
        "records": records_saved,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


# ── Orchestrator ──────────────────────────────────────────────

def run_daily_collection(
    model: str = "qwen2.5:7b",
    base_url: str = "http://localhost:11434",
    dry_run: bool = False,
    specific_job: Optional[str] = None,
    max_priority: int = 3,
) -> dict:
    """
    Main entry point. Runs all scheduled daily jobs.
    Returns summary dict.
    """
    from daily_jobs import get_jobs_by_priority, DAILY_JOBS

    state = _load_state()
    start_time = datetime.now()
    log.info("=" * 60)
    log.info(f"🌿 Daily collection starting — {start_time.strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)

    # Pick jobs to run
    if specific_job:
        jobs = [j for j in DAILY_JOBS if j["job_id"] == specific_job]
        if not jobs:
            log.error(f"Job '{specific_job}' not found.")
            return {"error": f"job {specific_job} not found"}
    else:
        jobs = get_jobs_by_priority(max_priority)

    log.info(f"📋 {len(jobs)} jobs queued")

    # Load agent
    if not dry_run:
        log.info(f"🤖 Loading agent (model: {model})...")
        try:
            executor = _load_agent(model=model, base_url=base_url)
            log.info("✅ Agent ready")
        except Exception as exc:
            log.error(f"❌ Agent failed to load: {exc}")
            return {"error": str(exc)}
    else:
        executor = None

    # Run jobs
    results = []
    total_records = 0
    for i, job in enumerate(jobs, 1):
        log.info(f"\n[{i}/{len(jobs)}] {job['label']}")
        result = run_job(job, executor, dry_run=dry_run)
        results.append(result)
        total_records += result.get("records", 0)
        state["job_history"][job["job_id"]] = result
        _save_state(state)
        if not dry_run:
            time.sleep(3)  # pause between jobs

    # Update state
    elapsed = (datetime.now() - start_time).seconds
    state["last_run"] = start_time.isoformat(timespec="seconds")
    state["total_runs"] = state.get("total_runs", 0) + 1
    state["total_records_collected"] = state.get("total_records_collected", 0) + total_records
    _save_state(state)

    summary = {
        "date": start_time.strftime("%Y-%m-%d"),
        "jobs_run": len(jobs),
        "jobs_succeeded": sum(1 for r in results if r["status"] in ("completed","dry_run")),
        "records_collected": total_records,
        "elapsed_seconds": elapsed,
    }
    log.info("\n" + "=" * 60)
    log.info(f"✅ Collection complete in {elapsed}s")
    log.info(f"   Jobs: {summary['jobs_succeeded']}/{summary['jobs_run']}")
    log.info(f"   Records collected: {total_records}")
    log.info("=" * 60)

    return summary


# ── Daemon mode ───────────────────────────────────────────────

def run_daemon(
    model: str,
    base_url: str,
    run_hour: int = 7,
    run_minute: int = 0,
) -> None:
    """
    Run scheduler as a daemon — waits until run_hour:run_minute each day,
    then runs the full collection. Loops indefinitely (Ctrl+C to stop).
    """
    log.info(f"🕐 Daemon started — will collect daily at {run_hour:02d}:{run_minute:02d}")
    log.info("   Press Ctrl+C to stop")

    while True:
        now = datetime.now()
        target = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        log.info(f"⏳ Next run in {int(wait_seconds//3600)}h {int((wait_seconds%3600)//60)}m "
                 f"(at {target.strftime('%Y-%m-%d %H:%M')})")

        try:
            time.sleep(wait_seconds)
        except KeyboardInterrupt:
            log.info("👋 Daemon stopped.")
            break

        try:
            run_daily_collection(model=model, base_url=base_url)
            # Print digest after each run
            print("\n" + build_digest())
        except Exception as exc:
            log.error(f"❌ Collection run failed: {exc}")


# ── CLI ───────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TOW Hyderabad — Daily Intelligence Scheduler"
    )
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model")
    parser.add_argument("--url", default="http://localhost:11434", help="Ollama URL")
    parser.add_argument("--dry-run", action="store_true", help="Show jobs without executing")
    parser.add_argument("--job", default=None, help="Run a single specific job by ID")
    parser.add_argument("--daemon", action="store_true", help="Run continuously on daily schedule")
    parser.add_argument("--digest", action="store_true", help="Print today's digest and exit")
    parser.add_argument("--hour", type=int, default=7, help="Daemon run hour (default: 7 AM)")
    parser.add_argument("--list-jobs", action="store_true", help="List all available jobs")
    parser.add_argument("--priority", type=int, default=3, help="Max priority to run (1=highest, 4=lowest)")
    args = parser.parse_args()

    if args.list_jobs:
        from daily_jobs import DAILY_JOBS
        print(f"\n📋 {len(DAILY_JOBS)} configured jobs:\n")
        for j in sorted(DAILY_JOBS, key=lambda x: x["priority"]):
            print(f"  [{j['priority']}] {j['job_id']:<35} {j['label']}")
            print(f"       frequency={j['frequency']}  save_as={j['save_as']}")
        return

    if args.digest:
        print(build_digest())
        return

    if args.daemon:
        run_daemon(model=args.model, base_url=args.url, run_hour=args.hour)
        return

    # Single run
    summary = run_daily_collection(
        model=args.model,
        base_url=args.url,
        dry_run=args.dry_run,
        specific_job=args.job,
        max_priority=args.priority,
    )
    print("\n" + build_digest())


if __name__ == "__main__":
    main()