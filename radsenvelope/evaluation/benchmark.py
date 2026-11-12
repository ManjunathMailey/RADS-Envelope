r"""
Stress-test benchmark on controlled-ambiguity reports.

    python -m radsenvelope.evaluation.benchmark --n 200 --extractor lexicon
    python -m radsenvelope.evaluation.benchmark --n 200 --extractor llm

Writes data/benchmark/results_<extractor>.json (served to the Evaluation view).
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
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "extractor": extractor,
            "samples": samples, "seed": seed, "summary": summary,
            "features": feature_scores(pairs, ("aphe", "washout", "capsule", "growth")),
            "errors": [r for r in rows if r["pred_category"] != r["gold_category"]][:25]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--extractor", choices=["lexicon", "llm", "auto"], default="lexicon")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    res = run(a.n, a.extractor, a.samples, a.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"results_{a.extractor}.json"
    path.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res["summary"], indent=1))
    print(json.dumps(res["features"], indent=1))
    print(f"Saved {path}")


if __name__ == "__main__":
    main()
