"""change_detector.py — thin shim delegating to intel.alerts.

Kept for backwards compatibility with scheduler.py and cli.py. New code should
import from intel.alerts directly.
"""
from __future__ import annotations


def get_unacknowledged(since_hours: int = 48) -> list:
    try:
        from intel.alerts import get_unacknowledged as _g
        from intel.db import init_db
        init_db()
        return _g(since_hours=since_hours)
    except Exception:
        return []


def format_alerts(alerts: list) -> str:
    try:
        from intel.alerts import format_alerts as _f
        return _f(alerts)
    except Exception:
        return "\n".join(str(a) for a in alerts) if alerts else "No alerts."


def run_detection() -> list:
    try:
        from intel.alerts import run_detection as _r
        from intel.db import init_db
        init_db()
        return _r()
    except Exception:
        return []
