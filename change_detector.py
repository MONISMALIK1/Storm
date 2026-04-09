"""
change_detector.py — Alert Engine
=================================
Scans CSVs for alerts: bad reviews, competitor moves, price threats.
"""

def get_unacknowledged(since_hours: int = 48) -> list:
    """Return a list of unacknowledged alerts (placeholder)."""
    return []

def format_alerts(alerts: list) -> str:
    """Format alerts to string (placeholder)."""
    if not alerts:
        return "No alerts."
    return "\n".join(str(a) for a in alerts)

def run_detection() -> list:
    """Run detection engine and return new alerts list (placeholder)."""
    return []
