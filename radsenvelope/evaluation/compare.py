"""
Side-by-side comparison of four systems on the same cases.

  B1    LLM-direct: the LLM gives features and the category in one call (baselines.py)
  B2    lexicon + rules: deterministic extractor, engine point category
  B3    LLM + rules: LLM extractor, engine point category only
  B4    hybrid: B1's category, replaced by the rule category from B1's own features when they
        disagree (post-hoc correction; derived from the B1 run, no extra model call)
  Ours  LLM + rules + Certainty Envelope: same point category as B3, plus the envelope and
        management-aware alerts

B3 and Ours share one pipeline run per case (they differ only in what is reported). B2, B3 and
Ours derive the category from the features with the engine, so their contradiction rate is zero
by construction; the impression consistency check is reported as evidence.
"""
from __future__ import annotations

import time

from radsenvelope.extraction.segment import split_sections
from radsenvelope.pipeline import Settings, analyse_report

from .baselines import llm_direct
from .metrics import feature_scores, system_summary

SYSTEMS = ("B1", "B2", "B3", "B4", "Ours")
FEATURE_KEYS = ("aphe", "washout", "capsule", "growth")


def _pred(result: dict) -> str:
    return result.get("acr_category") or result.get("status")


def _pipeline_row(case: dict, settings: Settings) -> tuple[dict, dict]:
    t = time.time()
    out = analyse_report(case["text"], settings)
    o = out["observations"][0]
    r = o["result"]
    row = {"id": case["id"], "gold": case["gold"], "pred": _pred(r), "envelope": r.get("envelope"),
           "critical": bool(r.get("decision_critical")), "any_unresolved": bool(r.get("unresolved_features")),
           "consistent": out["consistency"]["consistent"], "contradiction": False,
           "seconds": round(time.time() - t, 3), "size_mm": o["size_mm"],
           # kept so tolerance sensitivity and error analysis can be recomputed by the engine alone
           "features": o["features"], "size_tolerance_mm": o["size_tolerance_mm"], "defer_reasons": o["defer_reasons"],
           "evidence": {k: v.get("evidence", "") for k, v in o["extraction"].items() if isinstance(v, dict)},
           "size_evidence": o["extraction"].get("size_evidence", "")}
    return row, o["features"]


def hybrid_row(b1: dict) -> dict:
    """B4 (hybrid, slide 11 arm C), no new model call: keep B1's free-form category unless it
    contradicts the rule category computed from B1's own extracted features, in which case the
    rule category replaces it (post-hoc correction)."""
    corrected = b1.get("contradiction") is True
    return {**b1, "pred": b1["engine_category"] if corrected else b1["pred"],
            "contradiction": None if b1.get("contradiction") is None else False, "corrected": corrected}


def run(cases: list[dict], systems: tuple[str, ...] = SYSTEMS, samples: int = 1) -> dict:
    """cases: [{id, text, gold, gold_features?: {feature: state}, gold_size_mm?: float}]"""
    rows = {s: [] for s in systems}
    feats = {s: [] for s in systems}
    for c in cases:
        if "B2" in systems:
            row, f = _pipeline_row(c, Settings(extractor="lexicon"))
            rows["B2"].append(row)
            feats["B2"].append(f)
        if "B3" in systems or "Ours" in systems:
            row, f = _pipeline_row(c, Settings(extractor="llm", samples=samples))
            for s in ("B3", "Ours"):
                if s in systems:
                    r = dict(row)
                    if s == "B3":
                        r.update(envelope=None, critical=None, any_unresolved=None)
                    rows[s].append(r)
                    feats[s].append(f)
        if "B1" in systems:
            findings = split_sections(c["text"])[0] or c["text"]
            d = llm_direct(findings)
            rows["B1"].append({"id": c["id"], "gold": c["gold"], "pred": d["category"], "envelope": None,
                               "critical": None, "any_unresolved": None, "consistent": None,
                               "contradiction": d["contradiction"], "seconds": d.get("seconds"),
                               "size_mm": d["size_mm"], "engine_category": d["engine_category"], "error": d["error"],
                               "features": d["features"]})
            feats["B1"].append(d["features"] or {})
    if "B4" in systems:
        if "B1" not in rows:
            raise ValueError("B4 (hybrid) is derived from B1; include B1 in the systems")
        rows["B4"], feats["B4"] = [hybrid_row(r) for r in rows["B1"]], list(feats["B1"])
    result = {}
    for s in systems:
        summary = system_summary(rows[s], envelope=(s == "Ours"))
        gold_pairs = [(c["gold_features"], f) for c, f in zip(cases, feats[s]) if c.get("gold_features")]
        if gold_pairs:
            keys = tuple(k for k in FEATURE_KEYS if any(k in g for g, _ in gold_pairs))
            summary["features"] = feature_scores(
                [({k: v for k, v in g.items() if k in keys}, p) for g, p in gold_pairs], keys)
            summary["features_n"] = len(gold_pairs)
        sized = [(c["gold_size_mm"], r["size_mm"]) for c, r in zip(cases, rows[s]) if c.get("gold_size_mm") is not None]
        if sized:
            ok = sum(p is not None and abs(p - g) <= 0.5 for g, p in sized)
            summary["size_accuracy"] = {"k": ok, "n": len(sized), "value": round(ok / len(sized), 4), "tolerance_mm": 0.5}
        result[s] = {"summary": summary, "rows": rows[s]}
    if "B1" in systems:
        result["B1"]["summary"]["unparsed"] = sum(r["error"] is not None for r in rows["B1"])
    if "B4" in systems:
        result["B4"]["summary"]["corrected"] = sum(r["corrected"] for r in rows["B4"])
    sources = sorted({c.get("source") for c in cases if c.get("source")})
    if sources:                                             # per-source breakdown plus pooled (= the summaries above)
        result["per_source"] = {
            src: {s: system_summary([r for c, r in zip(cases, rows[s]) if c.get("source") == src], envelope=(s == "Ours"))
                  for s in systems} for src in sources}
    return result


def table(result: dict) -> list[dict]:
    """One flat row per system for printing."""
    def fmt(p):
        if not p or p.get("value") is None:
            return "-"
        lo, hi = p["ci95"]
        return f"{p['value']:.3f} [{lo:.3f}-{hi:.3f}]"
    out = []
    for s, r in result.items():
        if s == "per_source":
            continue
        m = r["summary"]
        contra = m["contradiction_rate"]
        out.append({
            "system": s, "accuracy [95% CI]": fmt(m["accuracy"]), "weighted_kappa": m["weighted_kappa"],
            "LR-5 sens": fmt(m["lr5_sensitivity"]), "LR-5 spec": fmt(m["lr5_specificity"]),
            "envelope coverage": fmt(m.get("envelope_coverage")), "mean envelope size": m.get("mean_envelope_size", "-"),
            "±1-band coverage": fmt(m["pm1_band_coverage"]),
            "contradiction rate": fmt(contra) + (f" (n={contra['n']})" if contra else ""),
            "alert rate": fmt(m.get("alert_rate")),
        })
    return out
