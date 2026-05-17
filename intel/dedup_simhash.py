"""Content hashing + SimHash near-duplicate detection."""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "this", "that", "these", "those", "it", "its", "be", "been", "being",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HASH_BITS = 64


def normalize(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", " ", text)
    t = re.sub(r"&[a-z]+;", " ", t)
    t = t.lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def tokens(text: str) -> list[str]:
    return [
        w for w in _TOKEN_RE.findall(normalize(text))
        if w not in _STOPWORDS and len(w) > 1
    ]


def content_hash(*parts: str) -> str:
    """Stable SHA-256 over normalized concatenation of parts."""
    joined = "||".join(normalize(p or "") for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _feature_hash(token: str) -> int:
    h = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def simhash(text: str) -> int:
    """64-bit SimHash for near-duplicate detection."""
    toks = tokens(text)
    if not toks:
        return 0
    weights = [0] * _HASH_BITS
    for tok in toks:
        h = _feature_hash(tok)
        for i in range(_HASH_BITS):
            weights[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, w in enumerate(weights):
        if w > 0:
            out |= 1 << i
    # Convert unsigned 64-bit to signed 64-bit (SQLite INTEGER range)
    if out >= (1 << 63):
        out -= (1 << 64)
    return out


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def is_near_duplicate(text: str, candidates: Iterable[int], threshold: int = 4) -> bool:
    """True if any candidate simhash is within `threshold` bits."""
    target = simhash(text)
    if target == 0:
        return False
    for c in candidates:
        if c and hamming_distance(target, c) <= threshold:
            return True
    return False
