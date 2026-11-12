r"""
Robustness test (rule-generated gold) on controlled-ambiguity reports.

The gold category of each generated report comes from the engine's own rule table applied to the
known feature vector, so agreement here is not clinical accuracy: it measures how robustly a
system recovers the features under varied phrasing, hedges, omissions and near-cut-off sizes.

    python -m radsenvelope.evaluation.benchmark --n 200 --extractor lexicon
    python -m radsenvelope.evaluation.benchmark --n 200 --extractor llm
    python -m radsenvelope.evaluation.benchmark --n 200 --compare     # B1 / B2 / B3 / Ours

Writes data/benchmark/results_<extractor>.json (served to the Evaluation view);
--compare writes data/benchmark/results_comparison.json.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from radsenvelope.engine.ruleset import FEATURES
from radsenvelope.pipeline import Settings, analyse_report

from .generator import generate
from .metrics import category_scores, feature_scores

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "benchmark"
# the gold labels are produced by the same rule table the systems use: this measures robustness of
# extraction to phrasing, hedges, omissions and near-cut-off sizes, not clinical accuracy
ROBUSTNESS_LABEL = "robustness test (rule-generated gold)"


def run(n: int, extractor: str, samples: int = 1, seed: int = 7) -> dict:
    cases = generate(n, seed)
    rows, pairs, size_ok, t0 = [], [], 0, time.time()
    for c in cases:
        out = analyse_report(c["report"], Settings(extractor=extractor, samples=samples))
        o = out["observations"][0]
        res = o["result"]
        pairs.append((c["gold_features"], o["features"]))
        size_ok += o["size_mm"] is not None and abs(o["size_mm"] - c["gold_size_mm"]) < 0.01
        rows.append({
            "id": c["id"], "report": c["report"],
            "gold_category": c["gold_category"], "pred_category": res.get("acr_category"),
            "gold_envelope": c["gold_envelope"], "pred_envelope": res.get("envelope"),
            "gold_critical": c["gold_decision_critical"], "pred_critical": bool(res.get("decision_critical")),
            "pred_any_unresolved": bool(res.get("unresolved_features")),
            "extractor": out["extractor"].get("used"),
        })
    summary = category_scores(rows)
    summary["size_accuracy"] = round(size_ok / n, 3)
    summary["seconds_per_report"] = round((time.time() - t0) / n, 3)
    from .provenance import run_meta
    return {**run_meta(), "label": ROBUSTNESS_LABEL, "extractor": extractor,
            "samples": samples, "seed": seed, "summary": summary,
            "features": feature_scores(pairs, ("aphe", "washout", "capsule", "growth")),
            "errors": [r for r in rows if r["pred_category"] != r["gold_category"]][:25]}


def compare(n: int, seed: int = 7, samples: int = 1) -> dict:
    """B1 / B2 / B3 / Ours on the same generated cases (gold category = ACR point category)."""
    from .compare import run
    cases = [{"id": c["id"], "text": c["report"], "gold": c["gold_category"], "gold_features": c["gold_features"],
              "gold_size_mm": c["gold_size_mm"]} for c in generate(n, seed)]
    from .provenance import run_meta
    return {**run_meta(), "label": ROBUSTNESS_LABEL, "n": n, "seed": seed,
            "samples": samples, "systems": run(cases, samples=samples)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--extractor", choices=["lexicon", "llm", "auto"], default="lexicon")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--compare", action="store_true", help="run B1, B2, B3 and Ours side by side")
    a = ap.parse_args()
    if a.compare:
        from .compare import table
        res = compare(a.n, a.seed, a.samples)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / "results_comparison.json"
        path.write_text(json.dumps(res, indent=1), encoding="utf-8")
        for t in table(res["systems"]):
            print(json.dumps(t, ensure_ascii=False))
        print(f"Saved {path}")
        return
    res = run(a.n, a.extractor, a.samples, a.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"results_{a.extractor}.json"
    path.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res["summary"], indent=1))
    print(json.dumps(res["features"], indent=1))
    print(f"Saved {path}")


if __name__ == "__main__":
    main()
