"""Scope guard: findings that place an observation outside the core diagnostic table."""
from __future__ import annotations

import re

from radsenvelope.engine.ruleset import get_ruleset

_NEGATED = re.compile(r"\bno (evidence of )?(tumou?r in vein|targetoid\w*)", re.I)


def defer_reasons(text: str) -> list[str]:
    low = _NEGATED.sub("", text.lower())
    hits = []
    for keyword, reason in get_ruleset().defer_keywords().items():
        if not re.search(r"\b" + re.escape(keyword) + r"\b", low):
            continue
        if keyword.startswith("rim") and re.search(r"non-?\s?rim", low):
            continue
        if reason not in hits:
            hits.append(reason)
    return hits
