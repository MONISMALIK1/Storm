"""
dedup.py — Deduplication Engine
================================
Prevents duplicate records from being saved across any CSV database.
Uses content fingerprinting (SHA-256) stored in a local seen_hashes.json.
"""

import hashlib
import json
import os
import re

HASH_FILE = "seen_hashes.json"


def _load() -> dict:
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r") as f:
            return json.load(f)
    return {}


def _save(store: dict) -> None:
    with open(HASH_FILE, "w") as f:
        json.dump(store, f, indent=2)


def _fingerprint(text: str) -> str:
    """Normalise and hash text for fuzzy deduplication."""
    normalised = re.sub(r"\s+", " ", text.lower().strip())
    # Remove common noise words
    for word in ["the", "a", "an", "is", "in", "of", "and", "to", "for"]:
        normalised = re.sub(rf"\b{word}\b", "", normalised)
    normalised = re.sub(r"\s+", " ", normalised).strip()
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def is_duplicate(namespace: str, content: str) -> bool:
    """
    Check whether this content has already been seen in the given namespace.
    namespace: e.g. "reviews", "news", "competitors"
    content:   the main text to deduplicate against (review_text, headline, etc.)
    """
    store = _load()
    fp = _fingerprint(content)
    key = f"{namespace}:{fp}"
    return key in store


def mark_seen(namespace: str, content: str) -> str:
    """Mark content as seen and return its fingerprint."""
    store = _load()
    fp = _fingerprint(content)
    key = f"{namespace}:{fp}"
    store[key] = True
    _save(store)
    return fp


def check_and_mark(namespace: str, content: str) -> bool:
    """
    Combined check + mark. Returns True if it WAS a duplicate (skip it).
    Returns False if it's new (safe to save).
    """
    if is_duplicate(namespace, content):
        return True  # duplicate — skip
    mark_seen(namespace, content)
    return False  # new — save it


def reset_namespace(namespace: str) -> int:
    """Clear all hashes for a given namespace. Returns count removed."""
    store = _load()
    keys_to_remove = [k for k in store if k.startswith(f"{namespace}:")]
    for k in keys_to_remove:
        del store[k]
    _save(store)
    return len(keys_to_remove)


def stats() -> dict:
    store = _load()
    counts: dict[str, int] = {}
    for key in store:
        ns = key.split(":")[0]
        counts[ns] = counts.get(ns, 0) + 1
    return counts