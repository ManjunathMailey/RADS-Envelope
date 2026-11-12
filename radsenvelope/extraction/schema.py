"""Extraction schema shared by every extractor, plus evidence grounding."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from radsenvelope.engine.ruleset import FEATURES

State = Literal["present", "absent", "uncertain", "not_documented"]


class Feature(BaseModel):
    state: State
    evidence: str = Field(default="", description="Exact words copied from the report; empty if not documented")


class Extraction(BaseModel):
    size_mm: Optional[float] = Field(description="Largest observation diameter in millimetres; null if not stated")
    size_evidence: str = ""
    aphe: Feature
    washout: Feature
    capsule: Feature
    growth: Feature
    af_malignant: Feature
    af_benign: Feature

    def states(self) -> dict:
        return {k: getattr(self, k).state for k in FEATURES}


_STOP = {"a", "an", "the", "and", "with", "of", "on", "in", "is", "are", "was"}
MIN_OVERLAP = 0.8


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if w not in _STOP]


def is_grounded(evidence: str, text: str) -> bool:
    """A span is grounded if it occurs verbatim, or if at least 80% of its content words
    occur within a single sentence of the source text."""
    ev = " ".join(evidence.lower().split())
    if not ev or ev in " ".join(text.lower().split()):
        return True
    words = _words(ev)
    if not words:
        return False
    for sentence in re.split(r"(?<!\d)[.!?](?!\d)|\n", text):
        vocab = set(_words(sentence))
        if sum(w in vocab for w in words) / len(words) >= MIN_OVERLAP:
            return True
    return False


def grounding_errors(ex: Extraction, text: str) -> list[str]:
    errs = [f"{k}: {getattr(ex, k).evidence!r}" for k in FEATURES if not is_grounded(getattr(ex, k).evidence, text)]
    if ex.size_evidence and not is_grounded(ex.size_evidence, text):
        errs.append(f"size: {ex.size_evidence!r}")
    return errs
