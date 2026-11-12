"""
End-to-end pipeline: report text -> segmentation -> extraction (+ consensus) -> scope guard
-> engine -> exam summary -> rule-consistent impression -> consistency check.

Used by the API, the evaluation scripts and the command line, so every surface runs the same code.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from radsenvelope.engine.envelope import Observation, analyse
from radsenvelope.engine.exam import summarise
from radsenvelope.engine.ruleset import FEATURES, get_ruleset
from radsenvelope.extraction import consensus, lexicon, llm
from radsenvelope.extraction.schema import Extraction, grounding_errors
from radsenvelope.extraction.scope import defer_reasons
from radsenvelope.extraction.segment import split_observations, split_sections, stated_categories
from radsenvelope.generation import impression


@dataclass
class Settings:
    extractor: str = "auto"            # auto | llm | lexicon
    samples: int = 1                   # >1 enables self-consistency
    size_tolerance_mm: float = 2.0
    high_risk: bool = True


def _extract(text: str, s: Settings) -> tuple[Extraction, dict, dict]:
    info: dict = {"requested": s.extractor}
    if s.extractor in ("auto", "llm"):
        ok, msg = llm.available()
        if ok:
            try:
                if s.samples > 1:
                    draws, secs = llm.sample(text, s.samples)
                    ex, conf = consensus.merge(draws)
                    info.update(used=f"LLM ({llm.MODEL}) x{s.samples} self-consistency", seconds=round(secs, 2))
                else:
                    ex, secs = llm.extract(text)
                    ex, conf = consensus.merge([ex])
                    info.update(used=f"LLM ({llm.MODEL})", seconds=round(secs, 2))
                return ex, conf, info
            except Exception as e:
                msg = f"LLM extraction failed: {e}"
        if s.extractor == "llm":
            raise RuntimeError(msg)
        info["fallback_reason"] = msg
    t = time.time()
    ex, conf = consensus.merge([lexicon.extract(text)])
    info.update(used="Lexicon (deterministic)", seconds=round(time.time() - t, 3))
    return ex, conf, info


def run_observation(label: str, features: dict, size_mm, tolerance: float, high_risk: bool,
                    defer: list[str]) -> dict:
    obs = Observation({k: features.get(k, "not_documented") for k in FEATURES}, size_mm,
                      tolerance, high_risk, defer, label)
    return analyse(obs)


def finalize(observations: list[dict]) -> dict:
    """Exam summary, generated impression and its consistency check for analysed observations."""
    results = [o["result"] for o in observations]
    text = impression.generate(observations)
    return {"exam": summarise(results), "impression": text,
            "consistency": impression.verify(text, observations)}


def analyse_report(report: str, settings: Settings | None = None) -> dict:
    s = settings or Settings()
    t0 = time.time()
    findings, impression_text = split_sections(report)
    segments = split_observations(findings)
    stated = stated_categories(impression_text)
    observations, extractor_info = [], []
    for i, seg in enumerate(segments):
        ex, conf, info = _extract(seg.text, s)
        extractor_info.append(info)
        tolerance = s.size_tolerance_mm + conf["size"]["spread_mm"] / 2
        defer = defer_reasons(seg.text)
        result = run_observation(seg.label, ex.states(), ex.size_mm, tolerance, s.high_risk, defer)
        own = stated[i] if len(stated) == len(segments) else (stated[0] if len(segments) == 1 and stated else None)
        audit = None
        if own and result["status"] == "assigned":
            audit = {"stated": own, "computed": result["acr_category"],
                     "contradiction": own != result["acr_category"],
                     "stated_in_envelope": own in result["envelope"]}
        observations.append({
            "label": seg.label, "text": seg.text, "size_mm": ex.size_mm,
            "size_tolerance_mm": tolerance, "defer_reasons": defer,
            "features": ex.states(), "extraction": ex.model_dump(), "confidence": conf,
            "grounding_errors": grounding_errors(ex, seg.text), "result": result, "audit": audit,
        })
    out = finalize(observations)
    return {
        "report": report, "findings": findings, "stated_impression": impression_text,
        "observations": observations, **out,
        "extractor": extractor_info[0] if extractor_info else {},
        "settings": s.__dict__, "rules": get_ruleset().label,
        "elapsed_seconds": round(time.time() - t0, 2),
    }
