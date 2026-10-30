"""Prompt-injection guard: invoice text is untrusted data and is scanned for instruction-like content."""
from __future__ import annotations

import re

SUSPICIOUS_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)\s+instructions?",
    r"disregard\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)?\s*(?:instructions?|rules?)",
    r"approve\s+(?:this|the)\s+invoice",
    r"auto[-\s]?approve",
    r"mark\s+(?:this|the)\s+invoice\s+as\s+(?:approved|paid|verified)",
    r"(?:reveal|print|show)\s+(?:your\s+|the\s+)?system\s+prompt",
    r"override\s+(?:the\s+)?(?:validation|checks?|rules?|limits?)",
    r"bypass\s+(?:the\s+)?(?:validation|checks?|approval)",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+(?:an?\s+)?(?:admin|administrator|manager|approver)",
    r"skip\s+(?:the\s+)?(?:checks?|validation|approval)",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in SUSPICIOUS_PATTERNS]


def scan(text: str | None) -> list[str]:
    """Return the suspicious phrases found (verbatim snippets). Empty list means nothing found."""
    if not text:
        return []
    normalised = re.sub(r"\s+", " ", text)
    hits = []
    for pattern in _COMPILED:
        for m in pattern.finditer(normalised):
            hits.append(m.group(0))
    return sorted(set(hits))
