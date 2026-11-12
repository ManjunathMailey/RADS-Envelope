"""
Certainty Envelope.

Given an observation whose features may be present, absent, uncertain or not documented,
and whose size is known only within a tolerance, compute:

  * the official point category (ACR tie-break: an uncertain feature is treated as absent),
  * the envelope: the exact set of categories reachable over every completion of the
    unresolved features and every size inside the tolerance interval,
  * for each reachable category, a minimal witness (the fewest assumptions that reach it),
  * the management classes the envelope spans and whether it is decision-critical,
  * decisive questions ranked by expected reduction in management classes,
  * single-feature counterfactuals ("what flips it").

The domain is tiny (at most 2^6 completions x a handful of size points), so the envelope
is computed by exact enumeration, not approximation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from .ruleset import FEATURE_LABELS, FEATURES, MAJOR_FEATURES, SHORT_LABELS, RuleSet, get_ruleset, rank

PRESENT, ABSENT, UNCERTAIN, NOT_DOCUMENTED = "present", "absent", "uncertain", "not_documented"
STATES = (PRESENT, ABSENT, UNCERTAIN, NOT_DOCUMENTED)

QUESTIONS = {
    "aphe": "Is there nonrim arterial phase hyperenhancement?",
    "washout": "Is the washout real and nonperipheral?",
    "capsule": "Is there an enhancing capsule?",
    "growth": "Is there threshold growth compared with prior imaging?",
    "af_malignant": "Are ancillary features favouring malignancy present?",
    "af_benign": "Are ancillary features favouring benignity present?",
}


@dataclass
class Observation:
    features: dict                      # feature -> state
    size_mm: float | None
    size_tolerance_mm: float = 2.0
    high_risk: bool = True
    defer_reasons: list = field(default_factory=list)
    label: str = "Observation 1"


def resolved(feature: str, state: str) -> bool | None:
    """True/False for a settled feature, None for one the envelope must enumerate.
    Ancillary features are optional in LI-RADS: not documented means not used."""
    if feature.startswith("af_") and state == NOT_DOCUMENTED:
        return False
    return {PRESENT: True, ABSENT: False}.get(state)


def point_assumption(obs: Observation) -> dict:
    return {k: bool(resolved(k, obs.features.get(k, NOT_DOCUMENTED))) for k in FEATURES}


def size_points(size: float, tolerance: float, cutoffs: list[float]) -> list[float]:
    """Representative sizes covering every bucket that the interval [size-tol, size+tol] touches."""
    lo, hi = max(size - tolerance, 0.1), size + tolerance
    pts = {size, lo, hi}
    for c in cutoffs:
        if lo < c <= hi:
            pts.update({c - 0.01, c})
    return sorted(pts)


def completions(obs: Observation, fixed: dict | None = None, tolerance: float | None = None):
    """Yield (features, size, assumptions) for every completion of the unresolved inputs."""
    rs = get_ruleset()
    fixed = fixed or {}
    tol = obs.size_tolerance_mm if tolerance is None else tolerance
    base = {k: resolved(k, obs.features.get(k, NOT_DOCUMENTED)) for k in FEATURES}
    base.update({k: v for k, v in fixed.items() if k != "size"})
    open_feats = [k for k in FEATURES if base[k] is None]
    sizes = [fixed["size"]] if "size" in fixed else size_points(obs.size_mm, tol, rs.cutoffs)
    for combo in product((False, True), repeat=len(open_feats)):
        f = dict(base)
        f.update(zip(open_feats, combo))
        assumed = [k for k, v in zip(open_feats, combo) if v]          # features assumed present
        for s in sizes:
            yield f, s, assumed


def envelope(obs: Observation, fixed: dict | None = None, tolerance: float | None = None,
             ruleset: RuleSet | None = None) -> set[str]:
    rs = ruleset or get_ruleset()
    return {rs.categorize(f, s) for f, s, _ in completions(obs, fixed, tolerance)}


def witnesses(obs: Observation, ruleset: RuleSet) -> dict:
    """For each reachable category, the completion needing the fewest departures from the
    ACR point assumption (features assumed present, size moved across a cut-off)."""
    best: dict[str, tuple] = {}
    base_bucket = ruleset.bucket(obs.size_mm)
    for f, s, assumed in completions(obs):
        c = ruleset.categorize(f, s)
        size_moved = ruleset.bucket(s) != base_bucket
        # a hedged feature ("possible washout") is a cheaper assumption than an undocumented one
        cost = sum(0.9 if obs.features.get(k) == UNCERTAIN else 1.0 for k in assumed) + (1.0 if size_moved else 0.0)
        if c not in best or cost < best[c][0]:
            best[c] = (cost, assumed, s if size_moved else None)
    out = {}
    for c, (cost, assumed, s) in best.items():
        parts = [f"{SHORT_LABELS[k]} present" for k in assumed]
        if s is not None:
            parts.append(f"measured {ruleset.bucket(s)} mm")
        out[c] = {"assumptions": len(parts), "if": parts or ["as documented"]}
    return out


def analyse(obs: Observation, ruleset: RuleSet | None = None) -> dict:
    rs = ruleset or get_ruleset()
    meta = {"rules": rs.label, "size_tolerance_mm": obs.size_tolerance_mm, "label": obs.label}
    if obs.defer_reasons:
        return {"status": "defer", "reasons": list(obs.defer_reasons), **meta}
    if obs.size_mm is None:
        return {"status": "not_assignable", "reasons": ["Observation size is not documented."], **meta}
    if not obs.high_risk:
        return {"status": "not_applicable",
                "reasons": ["LI-RADS applies only to patients at high risk of HCC (e.g. cirrhosis)."], **meta}

    mg = lambda cats: {rs.management(c) for c in cats}
    assumed = point_assumption(obs)
    point = rs.categorize(assumed, obs.size_mm)
    env = envelope(obs, ruleset=rs)
    management = mg(env)

    questions = []
    for k in FEATURES:
        if resolved(k, obs.features.get(k, NOT_DOCUMENTED)) is not None:
            continue
        yes, no = envelope(obs, {k: True}, ruleset=rs), envelope(obs, {k: False}, ruleset=rs)
        gain = len(management) - (len(mg(yes)) + len(mg(no))) / 2
        questions.append({"feature": k, "question": QUESTIONS[k], "if_yes": sorted(yes, key=rank),
                          "if_no": sorted(no, key=rank), "gain": round(gain, 2)})
    exact = envelope(obs, tolerance=0.0, ruleset=rs)
    if len(mg(exact)) < len(management):
        questions.append({"feature": "size", "question": "Re-measure the observation: its size is close to a cut-off.",
                          "if_exact": sorted(exact, key=rank), "gain": float(len(management) - len(mg(exact)))})
    questions = sorted((q for q in questions if q["gain"] > 0), key=lambda q: -q["gain"])

    flips = []
    for k in FEATURES:
        cur = resolved(k, obs.features.get(k, NOT_DOCUMENTED))
        if cur is None:
            continue
        alt = dict(assumed)
        alt[k] = not cur
        c = rs.categorize(alt, obs.size_mm)
        if c != point:
            flips.append({"feature": k, "label": FEATURE_LABELS[k], "to": ABSENT if cur else PRESENT, "category": c})

    unresolved = [k for k in FEATURES if resolved(k, obs.features.get(k, NOT_DOCUMENTED)) is None]
    near_cutoff = len({rs.bucket(s) for s in size_points(obs.size_mm, obs.size_tolerance_mm, rs.cutoffs)}) > 1
    return {
        "status": "assigned",
        "acr_category": point,
        "meaning": rs.meaning(point),
        "trace": rs.trace(assumed, obs.size_mm),
        "envelope": sorted(env, key=rank),
        "witnesses": witnesses(obs, rs),
        "management": [{"category": c, "action": rs.management(c)} for c in sorted(env, key=rank)],
        "decision_critical": len(management) > 1,
        "unresolved_features": unresolved,
        "tie_break_features": [k for k in MAJOR_FEATURES if k in unresolved],
        "near_size_cutoff": near_cutoff,
        "decisive_questions": questions[:3],
        "what_flips_it": flips,
        **meta,
    }
