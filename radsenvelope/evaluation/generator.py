"""
Controlled-ambiguity stress-test generator.

Builds reports from a gold feature vector using varied clinical phrasings, with deliberate
hedges, omissions, unit changes and near-threshold sizes. Because the gold vector is known,
the gold category and the gold envelope are known exactly. This set stress-tests extractors;
it is not a substitute for real reports (see real_cases.py).
"""
from __future__ import annotations

import random

from radsenvelope.engine.envelope import Observation, analyse
from radsenvelope.engine.ruleset import FEATURES

PHRASES = {
    "aphe": {
        "present": ["nonrim arterial phase hyperenhancement", "non-rim arterial phase hyperenhancement",
                    "arterial phase hyperenhancement", "avid nonrim arterial enhancement",
                    "hyperenhancement on late arterial phase images"],
        "absent": ["no arterial phase hyperenhancement", "without arterial phase hyperenhancement"],
        "uncertain": ["possible arterial phase hyperenhancement", "questionable arterial phase hyperenhancement"],
    },
    "washout": {
        "present": ["nonperipheral washout", "non-peripheral washout on the portal venous phase",
                    "washout on the delayed phase", "contrast that washes out by the portal venous phase"],
        "absent": ["no washout", "no washout appearance"],
        "uncertain": ["possible subtle washout", "equivocal washout", "questionable washout on the delayed phase"],
    },
    "capsule": {
        "present": ["an enhancing capsule", "an enhancing capsule on the delayed phase"],
        "absent": ["no enhancing capsule", "no capsule"],
        "uncertain": ["a questionable thin capsule", "possible enhancing capsule"],
    },
    "growth": {
        "present": ["consistent with threshold growth", "increased from {prev} mm five months ago, threshold growth"],
        "absent": ["stable compared with the prior study", "unchanged from the prior examination"],
        "uncertain": ["possible interval growth"],
        "not_documented_hint": ["No prior imaging is available for comparison."],
    },
}
SEGMENTS = ["II", "III", "IVa", "V", "VI", "VII", "VIII"]
STATE_WEIGHTS = {"present": 0.45, "absent": 0.3, "uncertain": 0.15, "not_documented": 0.10}


def _pick_state(rng: random.Random) -> str:
    return rng.choices(list(STATE_WEIGHTS), weights=STATE_WEIGHTS.values())[0]


def _size(rng: random.Random) -> float:
    if rng.random() < 0.35:                                   # near a cut-off on purpose
        return rng.choice([9, 9.5, 10, 10.5, 19, 19.5, 20, 21])
    return float(rng.randint(6, 45))


def make_case(rng: random.Random, idx: int) -> dict:
    gold = {k: _pick_state(rng) for k in ("aphe", "washout", "capsule", "growth")}
    gold.update(af_malignant="not_documented", af_benign="not_documented")
    size = _size(rng)
    use_cm = rng.random() < 0.3
    size_txt = f"{size / 10:g} cm" if use_cm else f"{size:g} mm"
    seg = rng.choice(SEGMENTS)
    with_parts, sentences = [], []
    for k in ("aphe", "washout", "capsule"):
        st = gold[k]
        if st == "not_documented":
            continue
        phrase = rng.choice(PHRASES[k][st])
        (with_parts if st == "present" else sentences).append(phrase)
    g = gold["growth"]
    if g == "not_documented":
        if rng.random() < 0.5:
            sentences.append(PHRASES["growth"]["not_documented_hint"][0].rstrip("."))
    else:
        sentences.append(rng.choice(PHRASES["growth"][g]).format(prev=max(int(size * 0.6), 5)))
    text = f"Segment {seg}: {size_txt} observation"
    if with_parts:
        text += " with " + (", ".join(with_parts[:-1]) + " and " + with_parts[-1] if len(with_parts) > 1 else with_parts[0])
    text += ". " + " ".join(s[0].upper() + s[1:] + "." for s in sentences)
    result = analyse(Observation(gold, size, 2.0))
    return {"id": f"B{idx:04d}", "report": text.strip(), "gold_features": gold, "gold_size_mm": size,
            "gold_category": result["acr_category"], "gold_envelope": result["envelope"],
            "gold_decision_critical": result["decision_critical"]}


def generate(n: int = 200, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    return [make_case(rng, i + 1) for i in range(n)]
