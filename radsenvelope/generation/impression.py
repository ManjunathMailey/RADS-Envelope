"""
Rule-consistent impression generation.

The impression is produced deterministically from engine output, never by the language model,
so the category it states is the category the rules computed. `verify()` parses the generated
text back and checks that claim; the result is reported with every analysis.
"""
from __future__ import annotations

import re

from radsenvelope.engine.ruleset import SHORT_LABELS, get_ruleset

_CAT_IN_TEXT = re.compile(r"LI-RADS (\d)\b")


def _features_sentence(result: dict, features: dict) -> str:
    rs = get_ruleset()
    present = [SHORT_LABELS[k] for k, v in features.items() if v == "present" and not k.startswith("af_")]
    absent = [SHORT_LABELS[k] for k, v in features.items() if v == "absent" and not k.startswith("af_")]
    bits = []
    if present:
        bits.append("with " + ", ".join(present))
    if absent:
        bits.append("without " + ", ".join(absent))
    return "; ".join(bits)


def observation_lines(index: int, label: str, size_mm, features: dict, result: dict) -> list[str]:
    rs = get_ruleset()
    head = f"{index}. {label}" + (f", {size_mm:g} mm observation" if size_mm else "")
    if result["status"] != "assigned":
        why = "; ".join(result.get("reasons", []))
        return [f"{head}: LI-RADS category not assigned automatically ({why}). Radiologist review required."]
    cat = result["acr_category"]
    desc = _features_sentence(result, features)
    lines = [f"{head}{(' ' + desc) if desc else ''}: LI-RADS {cat[-1]} ({rs.meaning(cat)})."]
    tb = result.get("tie_break_features", [])
    if tb and len(result["envelope"]) > 1:      # mention the tie-break only where it matters
        hedged = [SHORT_LABELS[k] for k in tb if features.get(k) == "uncertain"]
        missing = [SHORT_LABELS[k] for k in tb if features.get(k) == "not_documented"]
        notes = []
        if hedged:
            notes.append(f"{', '.join(hedged)} equivocal")
        if missing:
            notes.append(f"{', '.join(missing)} not assessed")
        lines.append(f"   {'; '.join(notes).capitalize()}; treated as absent per {rs.label}.")
    others = [c for c in result["envelope"] if c != cat]
    if others:
        alt = "; ".join(f"{c} if {' and '.join(result['witnesses'][c]['if'])}" for c in others)
        lines.append(f"   Could be {alt}.".replace(">=", "≥"))
    lines.append(f"   Recommendation: {rs.management(cat)}.")
    if result["decision_critical"] and result["decisive_questions"]:
        q = result["decisive_questions"][0]["question"]
        lines.append(f"   Decision-critical uncertainty: {q}")
    return lines


_GROWTH_OUTCOME = {
    "threshold_growth": "threshold growth",
    "threshold_growth_uncertain": "threshold growth uncertain within measurement tolerance",
    "subthreshold_growth": "subthreshold growth (ancillary feature favouring malignancy)",
    "size_stability": "size stability (ancillary feature favouring benignity)",
    "no_threshold_growth": "no threshold growth",
}


def longitudinal_line(block: dict | None) -> str | None:
    """One line describing the comparison with a prior study; never states a category."""
    if not block or block.get("matching") in (None, "none"):
        return None
    head = f"   Compared with prior {block.get('prior_modality') or 'study'} ({block.get('prior_date') or 'undated'})"
    outcome = _GROWTH_OUTCOME.get(block.get("rule"))
    if outcome is None:
        return f"{head}: growth not assessed ({block.get('explanation', '').rstrip('.')})."
    line = (f"{head}: {block['prior_mm']:g} -> {block['current_mm']:g} mm "
            f"({block['percent_change']:+.0f}% in {block['interval_days']} days), {outcome}.")
    if block.get("prior_conflict"):
        line += " The report states otherwise; the report's statement is used."
    return line


def generate(observations: list[dict]) -> str:
    """observations: [{label, size_mm, features, result, longitudinal?}] in report order."""
    lines = ["IMPRESSION:"]
    for i, o in enumerate(observations, 1):
        lines += observation_lines(i, o["label"], o.get("size_mm"), o["features"], o["result"])
        extra = longitudinal_line(o.get("longitudinal"))
        if extra:
            lines.append(extra)
    return "\n".join(lines)


def verify(text: str, observations: list[dict]) -> dict:
    """Check that every category stated in the generated text equals the engine's category."""
    blocks = re.split(r"\n(?=\d+\. )", text.split("\n", 1)[1] if "\n" in text else "")
    checks = []
    for o, block in zip(observations, blocks):
        expected = o["result"].get("acr_category")
        m = _CAT_IN_TEXT.search(block.split("\n")[0])
        stated = f"LR-{m.group(1)}" if m else None
        checks.append({"label": o["label"], "engine": expected, "text": stated, "ok": stated == expected})
    return {"consistent": all(c["ok"] for c in checks) and len(checks) == len(observations), "checks": checks}
