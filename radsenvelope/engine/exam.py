"""Exam-level summary over several observations in one report."""
from __future__ import annotations

from .ruleset import rank


def summarise(results: list[dict]) -> dict:
    assigned = [r for r in results if r["status"] == "assigned"]
    highest = max((r["acr_category"] for r in assigned), key=rank, default=None)
    highest_possible = max((c for r in assigned for c in r["envelope"]), key=rank, default=None)
    return {
        "observations": len(results),
        "assigned": len(assigned),
        "highest_category": highest,
        "highest_possible": highest_possible,
        "decision_critical": [r["label"] for r in assigned if r["decision_critical"]],
        "needs_review": [r["label"] for r in results if r["status"] != "assigned"],
    }
