"""
Lexicon extractor: sentence- and clause-level keyword matching with negation and hedge
scoping. Fully deterministic. Used as the offline fallback and as the transparent baseline
against which the LLM extractor is evaluated.
"""
from __future__ import annotations

import re

from .schema import Extraction, Feature

HEDGES = r"\b(possible|possibly|probable|probably|questionable|equivocal|subtle|cannot be excluded|cannot exclude|may represent|indeterminate|suspected|likely|faint)\b"
NEGATIONS = r"\b(no|not|without|absent|negative for|lacks?)\b"

PATTERNS = {
    "aphe": r"(arterial (phase )?(hyper-?)?enhanc\w*|\baphe\b)",
    "washout": r"wash-?\s?out",
    "capsule": r"capsul\w*",
    "af_malignant": r"(restricted diffusion|diffusion restriction|mild-?moderate t2 hyperintensity|fat in mass|nodule-in-nodule|mosaic architecture|corona enhancement)",
    "af_benign": r"(size stability|parallels blood pool|iron in mass|marked t2 hyperintensity|undistorted vessels)",
}

SENT_SPLIT = re.compile(r"(?<=[.;\n])\s+")


def _sentences(report: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(report) if s.strip()]


def _clause_with(sentence: str, pattern: str) -> str:
    """The comma/'and'-separated clause that contains the match, for local negation scope."""
    parts = re.split(r",|\band\b|\bbut\b|\bwith\b", sentence, flags=re.I)
    for p in parts:
        if re.search(pattern, p, re.I):
            return p
    return sentence


def _state_for(report: str, pattern: str) -> Feature:
    for s in _sentences(report):
        m = re.search(pattern, s, re.I)
        if not m:
            continue
        clause = _clause_with(s, pattern)
        if pattern == PATTERNS["aphe"] and re.search(r"\brim\b", clause, re.I) and not re.search(r"non-?\s?rim", clause, re.I):
            return Feature(state="absent", evidence=clause.strip(" .;"))
        if pattern == PATTERNS["washout"] and re.search(r"(?<!non)(?<!non-)\bperipheral", clause, re.I):
            return Feature(state="absent", evidence=clause.strip(" .;"))
        if re.search(NEGATIONS, clause, re.I):
            return Feature(state="absent", evidence=clause.strip(" .;"))
        if re.search(HEDGES, clause, re.I):
            return Feature(state="uncertain", evidence=clause.strip(" .;"))
        return Feature(state="present", evidence=clause.strip(" .;"))
    return Feature(state="not_documented", evidence="")


def _growth(report: str) -> Feature:
    for s in _sentences(report):
        low = s.lower()
        if re.search(r"no prior|no previous|no comparison|first (study|examination)", low):
            return Feature(state="not_documented", evidence=s.strip(" .;"))
        if re.search(r"threshold growth|increased (in size )?from|interval (growth|increase)|enlarg|grown", low):
            if re.search(r"\bno\b|\bwithout\b", low):
                return Feature(state="absent", evidence=s.strip(" .;"))
            if re.search(HEDGES, low):
                return Feature(state="uncertain", evidence=s.strip(" .;"))
            return Feature(state="present", evidence=s.strip(" .;"))
        if re.search(r"\b(stable|unchanged|no interval change|no interval growth)\b", low):
            return Feature(state="absent", evidence=s.strip(" .;"))
    return Feature(state="not_documented", evidence="")


SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x\s*\d+(?:\.\d+)?\s*)?(mm|cm)\b", re.I)


def _size(report: str):
    best, ev = None, ""
    for m in SIZE.finditer(report):
        v = float(m.group(1)) * (10 if m.group(2).lower() == "cm" else 1)
        if best is None or v > best:
            best, ev = v, m.group(0)
    return best, ev


def extract(report: str) -> Extraction:
    size, ev = _size(report)
    feats = {k: _state_for(report, p) for k, p in PATTERNS.items()}
    return Extraction(size_mm=size, size_evidence=ev, growth=_growth(report), **feats)
