"""
Side-by-side comparison of four systems on the same cases.

  B1    LLM-direct: the LLM gives features and the category in one call (baselines.py)
  B2    lexicon + rules: deterministic extractor, engine point category
  B3    LLM + rules: LLM extractor, engine point category only
  B4    hybrid: B1's category, replaced by the rule category from B1's own features when they
        disagree (post-hoc correction; derived from the B1 run, no extra model call)
  Ours  LLM + rules + Certainty Envelope: same point category as B3, plus the envelope and
        management-aware alerts (since the pre-registration: the LLM-only ablation)
  OursC Ours-consensus, the pre-registered primary system: LLM + lexicon votes in the consensus step,
        rules and envelope (derived from the B3 and B2 extractions, no extra model call)

B3 and Ours share one pipeline run per case (they differ only in what is reported). B2, B3 and
Ours derive the category from the features with the engine, so their contradiction rate is zero
by construction; the impression consistency check is reported as evidence.
"""
from __future__ import annotations

import time

from radsenvelope.engine.ruleset import FEATURES
from radsenvelope.extraction.consensus import EXTRACTOR_DISAGREEMENT, combine_extractors
from radsenvelope.extraction.schema import Extraction
from radsenvelope.extraction.segment import split_sections
from radsenvelope.generation import impression
from radsenvelope.pipeline import Settings, analyse_report, run_observation

from .baselines import llm_direct
from .metrics import feature_scores, system_summary

SYSTEMS = ("B1", "B2", "B3", "B4", "Ours", "OursC")
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


BASE_TOLERANCE = 2.0


def _extraction(row: dict) -> Extraction:
    ev = row.get("evidence") or {}
    data = {"size_mm": row.get("size_mm"), "size_evidence": row.get("size_evidence") or ""}
    for k in FEATURES:
        data[k] = {"state": (row.get("features") or {}).get(k, "not_documented"), "evidence": ev.get(k, "") or ""}
    return Extraction.model_validate(data)


def consensus_row(llm_row: dict, lex_row: dict) -> dict:
    """Ours-consensus (pre-registered primary system) from the stored LLM (B3) and lexicon (B2) extractions
    of the same case, through the same combine_extractors step the app uses; no new model call."""
    spread = 2 * max(0.0, float(llm_row.get("size_tolerance_mm") or BASE_TOLERANCE) - BASE_TOLERANCE)
    conf = {k: {"source": None} for k in FEATURES}
    conf["size"] = {"values": [], "spread_mm": spread, "agreement": 1.0}
    ex, conf = combine_extractors(_extraction(llm_row), conf, _extraction(lex_row))
    tol = BASE_TOLERANCE + conf["size"]["spread_mm"] / 2
    states = ex.states()
    result = run_observation(llm_row["id"], states, ex.size_mm, tol, True, llm_row.get("defer_reasons") or [])
    obs = [{"label": llm_row["id"], "size_mm": ex.size_mm, "features": states, "result": result}]
    text = impression.generate(obs)
    return {"id": llm_row["id"], "gold": llm_row["gold"], "pred": _pred(result), "envelope": result.get("envelope"),
            "critical": bool(result.get("decision_critical")), "any_unresolved": bool(result.get("unresolved_features")),
            "consistent": impression.verify(text, obs)["consistent"], "contradiction": False,
            "seconds": (llm_row.get("seconds") or 0) + (lex_row.get("seconds") or 0), "size_mm": ex.size_mm,
            "features": states, "size_tolerance_mm": tol, "defer_reasons": llm_row.get("defer_reasons") or [],
            "evidence": {k: getattr(ex, k).evidence for k in FEATURES}, "size_evidence": ex.size_evidence,
            "disagreements": [k for k in FEATURES if (conf.get(k) or {}).get("source") == EXTRACTOR_DISAGREEMENT]}


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
    if "OursC" in systems:
        b3 = rows.get("B3") or rows.get("Ours")
        if b3 is None or "B2" not in rows:
            raise ValueError("Ours-consensus is derived from the LLM (B3) and lexicon (B2) runs; include both")
        rows["OursC"] = [consensus_row(a, b) for a, b in zip(b3, rows["B2"])]
        feats["OursC"] = [r["features"] for r in rows["OursC"]]
    return summarise(cases, systems, rows, feats)


ENVELOPE_SYSTEMS = ("Ours", "OursC")


def summarise(cases: list[dict], systems: tuple[str, ...], rows: dict, feats: dict) -> dict:
    result = {}
    for s in systems:
        summary = system_summary(rows[s], envelope=(s in ENVELOPE_SYSTEMS))
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
    if "OursC" in systems:
        result["OursC"]["summary"]["disagreement_cases"] = sum(bool(r["disagreements"]) for r in rows["OursC"])
    sources = sorted({c.get("source") for c in cases if c.get("source")})
    if sources:                                             # per-source breakdown plus pooled (= the summaries above)
        result["per_source"] = {
            src: {s: system_summary([r for c, r in zip(cases, rows[s]) if c.get("source") == src],
                                    envelope=(s in ENVELOPE_SYSTEMS))
                  for s in systems} for src in sources}
    return result


def add_consensus(results: dict, source_of=None) -> dict:
    """Add Ours-consensus to an existing comparison result from its stored B3 and B2 rows; every other
    arm's rows are kept exactly as they are (no rerun)."""
    systems = results["systems"]
    order = [s for s in SYSTEMS if s in systems or s == "OursC"]
    rows = {s: systems[s]["rows"] for s in order if s != "OursC"}
    rows["OursC"] = [consensus_row(a, b) for a, b in zip(rows["B3"], rows["B2"])]
    cases = [{"id": r["id"], "gold": r["gold"], "source": source_of(r["id"]) if source_of else None}
             for r in rows["B2"]]
    feats = {s: [r.get("features") or {} for r in rows[s]] for s in order}
    new = summarise(cases, tuple(order), rows, feats)
    for s in order:                                         # keep the original summaries of the existing arms
        if s != "OursC":
            new[s] = systems[s]
    return {**results, "systems": new, "consensus_added": True}


def main() -> None:
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Add Ours-consensus to stored comparison results (no new model calls).")
    ap.add_argument("results", type=Path, nargs="+")
    a = ap.parse_args()
    from .provenance import run_meta
    from .real_cases import source_of
    for path in a.results:
        res = json.loads(path.read_text(encoding="utf-8"))
        res = add_consensus(res, source_of if res.get("split") else None)
        res["consensus_provenance"] = {**run_meta(), "method": "derived from the stored B3 and B2 extractions"}
        path.write_text(json.dumps(res, indent=1), encoding="utf-8")
        for t in table({k: v for k, v in res["systems"].items() if k in ("B3", "Ours", "OursC")}):
            print(path.name, json.dumps(t, ensure_ascii=False))



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


if __name__ == "__main__":
    main()
