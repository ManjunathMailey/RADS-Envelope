"""
Self-consistency consensus: turning extractor disagreement into explicit uncertainty.

Two different things can make a feature uncertain:
  * report uncertainty  - the radiologist hedged ("possible washout");
  * extractor uncertainty - repeated extractions of the same text disagree.

Both are mapped onto the same "uncertain" state, so the Certainty Envelope covers both, and
each feature keeps a `source` so the UI can say which kind it is. Size disagreement widens
the size tolerance instead of being averaged away.
"""
from __future__ import annotations

from collections import Counter
from statistics import median

from radsenvelope.engine.ruleset import FEATURES

from .schema import Extraction, Feature

# when votes tie, keep the more cautious state
_TIE_ORDER = {"uncertain": 0, "present": 1, "absent": 2, "not_documented": 3}
MIN_AGREEMENT = 0.67


def merge(samples: list[Extraction]) -> tuple[Extraction, dict]:
    n = len(samples)
    merged, confidence = {}, {}
    for k in FEATURES:
        votes = Counter(getattr(s, k).state for s in samples)
        top, count = min(votes.items(), key=lambda kv: (-kv[1], _TIE_ORDER[kv[0]]))
        agreement = count / n
        contradictory = {"present", "absent"} <= set(votes)
        if n > 1 and (contradictory or agreement < MIN_AGREEMENT) and top != "not_documented":
            state, source = "uncertain", "extractor"
        else:
            state, source = top, ("report" if top == "uncertain" else None)
        evidence = next((getattr(s, k).evidence for s in samples
                         if getattr(s, k).state == top and getattr(s, k).evidence), "")
        merged[k] = Feature(state=state, evidence=evidence)
        confidence[k] = {"agreement": round(agreement, 2), "source": source, "votes": dict(votes)}

    sizes = [s.size_mm for s in samples if s.size_mm is not None]
    size = median(sizes) if sizes else None
    spread = (max(sizes) - min(sizes)) if sizes else 0.0
    size_evidence = next((s.size_evidence for s in samples if s.size_evidence), "")
    confidence["size"] = {"values": sizes, "spread_mm": round(spread, 2),
                          "agreement": round(len([x for x in sizes if x == size]) / n, 2) if sizes else 1.0}
    return Extraction(size_mm=size, size_evidence=size_evidence, **merged), confidence
