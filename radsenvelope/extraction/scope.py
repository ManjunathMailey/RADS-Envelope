"""Scope guard: findings that place an observation outside the core diagnostic table."""
from __future__ import annotations

import re

from radsenvelope.engine.ruleset import get_ruleset

_NEGATED = re.compile(r"\bno (evidence of )?(tumou?r in vein|targetoid\w*)", re.I)
# negated vein findings and non-enhancement, removed before the scope patterns are applied
_NEGATED_VEIN = re.compile(r"\b(?:no|without)\s+(?:evidence\s+of\s+)?(?:enhancing\s+)?(?:tumou?r\s+)?thrombus\b"
                           r"|\b(?:no|without)\s+(?:evidence\s+of\s+)?enhancing\s+soft[\s-]+tissue[^.;]*", re.I)
_NON_ENHANCING = re.compile(r"\bnon-?\s?enhanc\w*|\bnot\s+enhanc\w*|\bwithout\s+(?:any\s+)?enhancement\b", re.I)


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
    rs = get_ruleset()
    scoped = _NON_ENHANCING.sub("", _NEGATED_VEIN.sub("", low))
    for rule in rs.defer_patterns():
        if re.search(rule["pattern"], scoped, re.I) and rule["reason"] not in hits:
            hits.append(rule["reason"])
    for rule in rs.defer_conditions():
        if (re.search(rule["require_any"], low, re.I) and not re.search(rule["forbid_any"], low, re.I)
                and rule["reason"] not in hits):
            hits.append(rule["reason"])
    return hits
