"""Privacy detector — regex-based PII scanning with risk scoring.

Iron Rule: only files with risk == "safe" may auto-register on chain.
Everything else requires explicit human confirmation.

PII detection for the oasyce-sdk agent pipeline.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

# Pre-compiled PII patterns
_PATTERNS: Dict[str, re.Pattern] = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone_cn": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "id_card_cn": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "credit_card": re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    "ip_address": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    ),
    "api_key": re.compile(
        r"""(?:api[_-]?key|token|secret)[=:]\s*["']\w{16,}["']""", re.IGNORECASE
    ),
}

# Risk weight per pattern type (higher = more dangerous)
_WEIGHTS: Dict[str, int] = {
    "email": 1,
    "phone_cn": 2,
    "id_card_cn": 4,
    "credit_card": 4,
    "ip_address": 1,
    "api_key": 3,
}

# Opaque binary extensions — skip content scanning entirely.
# Structured data formats like sqlite/parquet are handled separately so they
# are never auto-classified safe just because the bytes are not plain text.
_OPAQUE_BINARY_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".heic", ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".pyc", ".pyo",
})

# Structured data files may store readable values inside non-text containers.
_STRUCTURED_DATA_EXTS = frozenset({
    ".db", ".sqlite", ".sqlite3", ".parquet",
})

# Max file size for PII scanning (16 MB)
_MAX_SCAN_SIZE = 16 * 1024 * 1024

_STRUCTURED_UNSCANNED_TYPE = "structured_unscanned"
_STRUCTURED_BYTES_PATTERN = re.compile(rb"[\x09\x0a\x0d\x20-\x7e]{4,}")


def scan_text(text: str) -> Dict[str, Any]:
    """Scan text for PII patterns. Returns findings dict."""
    findings: List[Dict[str, Any]] = []
    for name, pattern in _PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            findings.append({
                "type": name,
                "count": len(matches),
                "sample": matches[0],
            })
    return {
        "has_sensitive": len(findings) > 0,
        "findings": findings,
    }


def scan_file(path: str) -> Dict[str, Any]:
    """Scan a file for PII. Skips binary files and large files."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _OPAQUE_BINARY_EXTS:
        return {"has_sensitive": False, "findings": []}

    try:
        size = os.path.getsize(path)
        if size > _MAX_SCAN_SIZE:
            if ext in _STRUCTURED_DATA_EXTS:
                return {
                    "has_sensitive": True,
                    "findings": [{
                        "type": _STRUCTURED_UNSCANNED_TYPE,
                        "count": 1,
                        "sample": ext or os.path.basename(path),
                    }],
                }
            return {"has_sensitive": False, "findings": []}

        if ext in _STRUCTURED_DATA_EXTS:
            with open(path, "rb") as f:
                raw = f.read()
            text = _extract_structured_text(raw)
            if not text.strip():
                return {
                    "has_sensitive": True,
                    "findings": [{
                        "type": _STRUCTURED_UNSCANNED_TYPE,
                        "count": 1,
                        "sample": ext or os.path.basename(path),
                    }],
                }
        else:
            with open(path, "r", errors="ignore") as f:
                text = f.read()
    except OSError:
        if ext in _STRUCTURED_DATA_EXTS:
            return {
                "has_sensitive": True,
                "findings": [{
                    "type": _STRUCTURED_UNSCANNED_TYPE,
                    "count": 1,
                    "sample": ext or os.path.basename(path),
                }],
            }
        return {"has_sensitive": False, "findings": []}

    return scan_text(text)


def _extract_structured_text(raw: bytes) -> str:
    """Extract printable substrings from structured binary containers.

    This is intentionally conservative: if we cannot meaningfully inspect
    structured data, callers should treat the file as non-safe rather than
    auto-allow it through the privacy gate.
    """
    chunks = [
        match.group().decode("utf-8", errors="ignore")
        for match in _STRUCTURED_BYTES_PATTERN.finditer(raw)
    ]
    return "\n".join(chunk for chunk in chunks if chunk)


def risk_level(findings: Dict[str, Any]) -> str:
    """Compute risk level from findings: safe/low/medium/high/critical.

    Risk thresholds:
        safe     — no PII detected (auto-registerable)
        low      — score < 4 (IP/email only)
        medium   — score < 10
        high     — score < 20
        critical — score >= 20 (credit cards, API keys in bulk)
    """
    if not findings.get("has_sensitive"):
        return "safe"
    score = 0
    for item in findings["findings"]:
        if item["type"] == _STRUCTURED_UNSCANNED_TYPE:
            return "medium"
        weight = _WEIGHTS.get(item["type"], 1)
        score += weight * item["count"]
    if score >= 20:
        return "critical"
    if score >= 10:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def check_file(path: str) -> str:
    """One-shot: scan file → return risk level string."""
    return risk_level(scan_file(path))
