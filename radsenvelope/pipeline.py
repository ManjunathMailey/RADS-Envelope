"""
End-to-end pipeline: report text -> segmentation -> extraction (+ consensus) -> scope guard
-> optional comparison with a prior study -> engine -> exam summary -> rule-consistent
impression -> consistency check.

Used by the API, the evaluation scripts and the command line, so every surface runs the same code.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import date

from radsenvelope.engine import longitudinal
from radsenvelope.engine.envelope import NOT_DOCUMENTED, PRESENT, UNCERTAIN, Observation, analyse
from radsenvelope.engine.exam import summarise
from radsenvelope.engine.ruleset import FEATURES, get_ruleset
from radsenvelope.extraction import consensus, lexicon, llm
from radsenvelope.extraction.schema import Extraction, grounding_errors
from radsenvelope.extraction.scope import defer_reasons
from radsenvelope.extraction.segment import split_observations, split_sections, stated_categories
from radsenvelope.extraction.sizes import reconcile_size
from radsenvelope.generation import impression


@dataclass
class Settings:
    extractor: str = "auto"            # auto | llm | lexicon | consensus (LLM + lexicon)
    samples: int = 1                   # >1 enables self-consistency
    size_tolerance_mm: float = 2.0
    high_risk: bool = True


def _guarded_merge(draws: list[Extraction], text: str) -> tuple[Extraction, dict]:
    """Size integrity guard, then consensus. Each draw's size must be a size written in the
    report; a corrected draw keeps its original value in confidence["size"]["corrected_from"].
    Guarding before the merge keeps one misread draw from widening the size spread."""
    fixed, originals = [], []
    for d in draws:
        size, evidence, corrected = reconcile_size(d.size_mm, d.size_evidence, text)
        if corrected:
            originals.append(d.size_mm)
            d = d.model_copy(update={"size_mm": size, "size_evidence": evidence})
        fixed.append(d)
    ex, conf = consensus.merge(fixed)
    if originals:
        conf["size"]["corrected_from"] = originals[0]
        conf["size"]["corrected_values"] = originals
    return ex, conf


def _extract(text: str, s: Settings) -> tuple[Extraction, dict, dict]:
    if s.extractor == "consensus":
        return _extract_consensus(text, s)
    info: dict = {"requested": s.extractor}
    if s.extractor in ("auto", "llm"):
        ok, msg = llm.available()
        if ok:
            try:
                if s.samples > 1:
                    draws, secs = llm.sample(text, s.samples)
                    ex, conf = _guarded_merge(draws, text)
                    info.update(used=f"LLM ({llm.MODEL}) x{s.samples} self-consistency", seconds=round(secs, 2))
                else:
                    ex, secs = llm.extract(text)
                    ex, conf = _guarded_merge([ex], text)
                    info.update(used=f"LLM ({llm.MODEL})", seconds=round(secs, 2))
                return ex, conf, info
            except Exception as e:
                msg = f"LLM extraction failed: {e}"
        if s.extractor == "llm":
            raise RuntimeError(msg)
        info["fallback_reason"] = msg
    t = time.time()
    ex, conf = _guarded_merge([lexicon.extract(text)], text)
    info.update(used="Lexicon (deterministic)", seconds=round(time.time() - t, 3))
    return ex, conf, info


def _extract_consensus(text: str, s: Settings) -> tuple[Extraction, dict, dict]:
    """LLM sample(s) plus the lexicon as a second extractor (pre-registered method change)."""
    ex, conf, info = _extract(text, replace(s, extractor="auto"))
    info["requested"] = "consensus"
    if not info.get("used", "").startswith("LLM"):
        return ex, conf, info                                   # LLM unavailable: lexicon only, already used
    lex, _ = _guarded_merge([lexicon.extract(text)], text)
    ex, conf = consensus.combine_extractors(ex, conf, lex)
    info["used"] = info["used"] + " + lexicon consensus"
    info["disagreements"] = [k for k in FEATURES if (conf.get(k) or {}).get("source") == consensus.EXTRACTOR_DISAGREEMENT]
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


FROM_PRIOR = "From prior study"


def _is_segment(label: str) -> bool:
    return label.lower().startswith("segment ")


def match_prior(labels: list[str], prior_labels: list[str]) -> list[tuple[int | None, str]]:
    """Pair each current observation with a prior one: by segment label first, then by order.
    Order is used only when one of the two labels is not a segment label, so two observations
    in different liver segments are never compared."""
    used: set[int] = set()
    out: list[tuple[int | None, str]] = [(None, "none")] * len(labels)
    for i, lab in enumerate(labels):
        if _is_segment(lab):
            j = next((j for j, p in enumerate(prior_labels) if j not in used and p.lower() == lab.lower()), None)
            if j is not None:
                used.add(j)
                out[i] = (j, "segment")
    for i, lab in enumerate(labels):
        if out[i][0] is None and i < len(prior_labels) and i not in used \
                and not (_is_segment(lab) and _is_segment(prior_labels[i])):
            used.add(i)
            out[i] = (i, "order")
    return out


PRIOR_FEATURES = ("growth", "af_malignant", "af_benign")


def _prior_observations(prior: dict, s: Settings) -> list[tuple[str, float | None, float | None]]:
    """Segment and extract the prior report with the same extractor and the same size guard;
    only sizes are used. Returns (label, size_mm, size the extractor read if it was corrected)."""
    findings, _ = split_sections(prior.get("report") or "")
    if not findings.strip():
        return []
    single = replace(s, samples=1)
    out = []
    for seg in split_observations(findings):
        ex, conf, _ = _extract(seg.text, single)
        out.append((seg.label, ex.size_mm, conf["size"].get("corrected_from")))
    return out


def apply_prior(states: dict, comparison: dict) -> tuple[dict, dict]:
    """Merge a computed comparison into extracted feature states (a deliberate safety policy):
    the computed growth state fills in growth the report does not settle (not documented or
    hedged); an explicit report statement is kept, and a disagreement is flagged, not overridden.
    Ancillary flags from the comparison are OR-ed with the extracted ones."""
    merged = dict(states)
    reported, computed = states.get("growth", NOT_DOCUMENTED), comparison["growth_state"]
    applied, conflict = False, None
    if computed != NOT_DOCUMENTED:
        if reported in (NOT_DOCUMENTED, UNCERTAIN):
            merged["growth"], applied = computed, True
        elif computed in ("present", "absent") and computed != reported:
            conflict = (f"The report states threshold growth is {reported}, but the prior study gives "
                        f"{computed}. The report's value is kept; please check the comparison.")
    added = [k for k in ("af_malignant", "af_benign") if comparison[k] and merged.get(k) != PRESENT]
    for k in added:
        merged[k] = PRESENT
    return merged, {"applied": applied, "reported_growth": reported, "prior_conflict": conflict,
                    "ancillary_added": added}


def compare_with_prior(states: dict, size_mm, tolerance: float, prior_mm, prior_date, current_date,
                       modality, matching: str, prior_label=None, evidence: dict | None = None) -> tuple[dict, dict]:
    """Compare, merge, and build the longitudinal block. The block stores everything
    `recompare` needs: the prior measurement, dates, modality, the states the report gave
    (before the merge) and the states the merge produced."""
    cmp = longitudinal.compare(size_mm, current_date, prior_mm, prior_date, modality, tolerance)
    merged, merge = apply_prior(states, cmp)
    block = {"matching": matching, "prior_label": prior_label, "prior_date": prior_date,
             "current_date": current_date, **cmp, **merge,
             "reported_states": {k: states.get(k, NOT_DOCUMENTED) for k in PRIOR_FEATURES},
             "applied_states": {k: merged.get(k, NOT_DOCUMENTED) for k in PRIOR_FEATURES},
             "reported_evidence": dict(evidence or {})}
    return merged, block


def recompare(features: dict, size_mm, tolerance: float, block: dict | None) -> tuple[dict, dict | None]:
    """Redo the comparison after the radiologist edits the size or the tolerance changes.

    A prior-derived feature still holding the value the merge gave it is reset to the report's
    own value before re-merging; a feature the radiologist changed by hand is treated as an
    explicit statement, so the merge policy keeps it and flags any disagreement."""
    if not block or block.get("matching") in (None, "none") or block.get("prior_mm") is None:
        return features, block
    applied, reported = block.get("applied_states") or {}, block.get("reported_states") or {}
    base = dict(features)
    for k in PRIOR_FEATURES:
        if k in applied and features.get(k) == applied[k]:
            base[k] = reported.get(k, features.get(k))
    merged, new = compare_with_prior(base, size_mm, tolerance, block["prior_mm"], block.get("prior_date"),
                                     block.get("current_date"), block.get("prior_modality"), block["matching"],
                                     block.get("prior_label"), block.get("reported_evidence"))
    for k in ("prior_size_corrected_from",):
        if k in block:
            new[k] = block[k]
    return merged, new


def analyse_report(report: str, settings: Settings | None = None, prior: dict | None = None) -> dict:
    """prior (optional): {report, prior_date, current_date, modality}; dates are ISO yyyy-mm-dd."""
    s = settings or Settings()
    t0 = time.time()
    findings, impression_text = split_sections(report)
    segments = split_observations(findings)
    stated = stated_categories(impression_text)
    prior_obs = _prior_observations(prior, s) if prior else []
    matches = match_prior([seg.label for seg in segments], [p[0] for p in prior_obs]) if prior else []
    current_date = (prior or {}).get("current_date") or date.today().isoformat()
    observations, extractor_info = [], []
    for i, seg in enumerate(segments):
        ex, conf, info = _extract(seg.text, s)
        extractor_info.append(info)
        tolerance = s.size_tolerance_mm + conf["size"]["spread_mm"] / 2
        defer = defer_reasons(seg.text)
        states, extraction, grounding = ex.states(), ex.model_dump(), grounding_errors(ex, seg.text)
        block = None
        if prior:
            j, method = matches[i]
            block = {"matching": method, "prior_label": None, "prior_date": prior.get("prior_date"),
                     "current_date": current_date}
            if j is None:
                block.update(growth_state=NOT_DOCUMENTED, rule="no_match", applied=False, prior_conflict=None,
                             prior_modality=longitudinal.normalise_modality(prior.get("modality")),
                             current_mm=ex.size_mm, prior_mm=None,
                             explanation="No matching observation was found in the prior report.")
            else:
                evidence = {k: extraction[k]["evidence"] for k in PRIOR_FEATURES}
                states, block = compare_with_prior(states, ex.size_mm, tolerance, prior_obs[j][1],
                                                   prior.get("prior_date"), current_date, prior.get("modality"),
                                                   method, prior_obs[j][0], evidence)
                if prior_obs[j][2] is not None:
                    block["prior_size_corrected_from"] = prior_obs[j][2]
                for k in (["growth"] if block["applied"] else []) + block["ancillary_added"]:
                    extraction[k] = {"state": states[k], "evidence": FROM_PRIOR}
                    conf[k] = {**conf.get(k, {}), "source": block["source"] if k == "growth" else "prior"}
        result = run_observation(seg.label, states, ex.size_mm, tolerance, s.high_risk, defer)
        own = stated[i] if len(stated) == len(segments) else (stated[0] if len(segments) == 1 and stated else None)
        audit = None
        if own and result["status"] == "assigned":
            audit = {"stated": own, "computed": result["acr_category"],
                     "contradiction": own != result["acr_category"],
                     "stated_in_envelope": own in result["envelope"]}
        obs = {
            "label": seg.label, "text": seg.text, "size_mm": ex.size_mm,
            "size_tolerance_mm": tolerance, "defer_reasons": defer,
            "features": states, "extraction": extraction, "confidence": conf,
            "grounding_errors": grounding, "result": result, "audit": audit,
        }
        if block is not None:
            obs["longitudinal"] = block
        observations.append(obs)
    out = finalize(observations)
    res = {
        "report": report, "findings": findings, "stated_impression": impression_text,
        "observations": observations, **out,
        "extractor": extractor_info[0] if extractor_info else {},
        "settings": s.__dict__, "rules": get_ruleset().label,
        "elapsed_seconds": round(time.time() - t0, 2),
    }
    if prior:
        res["prior"] = {"report": prior.get("report"), "prior_date": prior.get("prior_date"),
                        "current_date": current_date,
                        "modality": longitudinal.normalise_modality(prior.get("modality"))}
    return res
