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


EXTRACTOR_DISAGREEMENT = "extractor disagreement"


def combine_extractors(primary: Extraction, confidence: dict, second: Extraction) -> tuple[Extraction, dict]:
    """Add a second extractor's vote (the lexicon) to the primary (LLM) consensus.

    * second extractor "not_documented" = abstain: the primary value stands;
    * same state: the value stands (the second extractor's evidence fills an empty one);
    * different state: the feature becomes "uncertain" with source "extractor disagreement", so
      the Certainty Envelope enumerates both readings;
    * size: the primary size is kept (the second one fills a missing size); if both are grounded and
      differ, the size spread grows so that the tolerance interval (base + spread / 2) reaches the
      second size, the same mechanism as the spread between repeated samples.
    Both inputs have already passed the size integrity guard."""
    conf = {k: dict(v) if isinstance(v, dict) else v for k, v in confidence.items()}
    merged = {}
    for k in FEATURES:
        p, q = getattr(primary, k), getattr(second, k)
        c = dict(conf.get(k) or {})
        c["second_extractor"] = q.state
        if q.state == "not_documented" or q.state == p.state:
            merged[k] = Feature(state=p.state, evidence=p.evidence or (q.evidence if q.state == p.state else ""))
        else:
            merged[k] = Feature(state="uncertain", evidence=p.evidence or q.evidence)
            c.update(source=EXTRACTOR_DISAGREEMENT, disagreement={"llm": p.state, "lexicon": q.state})
        conf[k] = c
    size_conf = dict(conf.get("size") or {"values": [], "spread_mm": 0.0, "agreement": 1.0})
    ps, qs = primary.size_mm, second.size_mm
    size, evidence = (ps, primary.size_evidence) if ps is not None else (qs, second.size_evidence)
    if ps is not None and qs is not None and abs(ps - qs) > 0.01:
        size_conf["spread_mm"] = round(max(float(size_conf.get("spread_mm") or 0.0), 2 * abs(ps - qs)), 2)
        size_conf["second_extractor_mm"] = qs
    conf["size"] = size_conf
    return Extraction(size_mm=size, size_evidence=evidence, **merged), conf
