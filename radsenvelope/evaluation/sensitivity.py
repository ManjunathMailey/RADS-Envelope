r"""
Size-tolerance sensitivity, recomputed by the engine from stored extractions (no LLM calls).

    python -m radsenvelope.evaluation.sensitivity data/real/results.comparison.dev.json
    python -m radsenvelope.evaluation.sensitivity data/benchmark/results_comparison.json

For tolerances 0, 1, 2 and 3 mm: alert rate (decision-critical), envelope coverage of the reference
category, mean envelope size and the share of observations whose size interval crosses a cut-off.
The point category does not depend on the tolerance; only the envelope does. Any size spread from
self-consistency is kept on top of the tested tolerance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from radsenvelope.pipeline import run_observation

from .metrics import NUMERIC, proportion

TOLERANCES = (0.0, 1.0, 2.0, 3.0)
BASE_TOLERANCE = 2.0


def tolerance_sensitivity(rows: list[dict], tolerances=TOLERANCES, base: float = BASE_TOLERANCE) -> list[dict]:
    """rows: the "Ours" rows of a comparison result (need features, size_mm, gold)."""
    rows = [r for r in rows if r.get("features") is not None]
    out = []
    for tol in tolerances:
        results = []
        for r in rows:
            extra = max(0.0, float(r.get("size_tolerance_mm") or base) - base)
            res = run_observation(r["id"], r["features"], r.get("size_mm"), tol + extra, True, r.get("defer_reasons") or [])
            results.append((r, res))
        assigned = [(r, x) for r, x in results if x["status"] == "assigned"]
        graded = [(r, x) for r, x in results if r["gold"] in NUMERIC]
        out.append({
            "tolerance_mm": tol, "cases": len(results),
            "alert_rate": proportion(sum(bool(x.get("decision_critical")) for _, x in results), len(results)),
            "envelope_coverage": proportion(sum(r["gold"] in (x.get("envelope") or []) for r, x in graded), len(graded)),
            "mean_envelope_size": round(sum(len(x["envelope"]) for _, x in assigned) / len(assigned), 3) if assigned else None,
            "near_cutoff_rate": proportion(sum(bool(x.get("near_size_cutoff")) for _, x in assigned), len(assigned)),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    res = json.loads(a.results.read_text(encoding="utf-8"))
    if res.get("split") in ("test", "all") and os.environ.get("RADS_RUN_TEST") != "1":
        raise SystemExit("Refusing to analyse held-out test results without RADS_RUN_TEST=1.")
    table = tolerance_sensitivity(res["systems"]["Ours"]["rows"])
    out = a.out or a.results.with_name(a.results.name.replace("results", "tolerance_sensitivity"))
    out.write_text(json.dumps({"source_results": a.results.name, "split": res.get("split"), "label": res.get("label"),
                               "prompt_hash": res.get("prompt_hash"), "table": table}, indent=1), encoding="utf-8")
    for t in table:
        print(json.dumps({"tol": t["tolerance_mm"], "alert": t["alert_rate"]["value"],
                          "coverage": t["envelope_coverage"]["value"], "mean_env": t["mean_envelope_size"],
                          "near_cutoff": t["near_cutoff_rate"]["value"]}))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
