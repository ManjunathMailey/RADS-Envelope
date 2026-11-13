r"""
Repeatability of the LLM pipeline on the development cases.

    python -m radsenvelope.evaluation.repeatability [--runs 3]

* Standard mode run --runs times in a row, and --runs times interleaved with the B1 (LLM-direct)
  call before each case (a different prompt in between changes the server's cache state).
  Reported: % of cases whose category and envelope are identical across the runs of each
  condition, and across all runs of both conditions.
* Thorough mode (3 samples) once: how often extractor disagreement (a feature whose confidence
  source is "extractor") widened the envelope relative to the first Standard run, and whether
  the widened envelope covered the reference category.
Development cases only; writes data/real/repeatability.dev.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from radsenvelope.extraction.segment import split_sections
from radsenvelope.pipeline import Settings, analyse_report

from .baselines import llm_direct
from .provenance import run_meta
from .real_cases import compare_cases, load, read_split, select_split

OUT = Path(__file__).resolve().parents[2] / "data" / "real" / "repeatability.dev.json"


def _run(case: dict, samples: int = 1) -> dict:
    o = analyse_report(case["text"], Settings(extractor="llm", samples=samples))["observations"][0]
    r = o["result"]
    return {"category": r.get("acr_category") or r.get("status"), "envelope": r.get("envelope") or [],
            "extractor_uncertain": [k for k, c in o["confidence"].items()
                                    if isinstance(c, dict) and c.get("source") == "extractor"]}


def identical_share(runs: list[list[dict]]) -> dict:
    n = len(runs[0]) if runs else 0
    same = [all((r[i]["category"], r[i]["envelope"]) == (runs[0][i]["category"], runs[0][i]["envelope"]) for r in runs)
            for i in range(n)]
    return {"cases": n, "identical": sum(same), "share": round(sum(same) / n, 4) if n else None}


def repeatability(cases: list[dict], runs: int = 3) -> dict:
    standard = [[_run(c) for c in cases] for _ in range(runs)]
    interleaved = []
    for _ in range(runs):
        row = []
        for c in cases:
            llm_direct(split_sections(c["text"])[0] or c["text"])
            row.append(_run(c))
        interleaved.append(row)
    thorough = [_run(c, samples=3) for c in cases]
    widened = []
    for c, base, th in zip(cases, standard[0], thorough):
        wider = len(th["envelope"]) > len(base["envelope"]) and bool(th["extractor_uncertain"])
        widened.append({"id": c["id"], "reference": c["gold"], "standard_envelope": base["envelope"],
                        "thorough_envelope": th["envelope"], "extractor_uncertain": th["extractor_uncertain"],
                        "widened": wider, "covers_reference": c["gold"] in th["envelope"],
                        "standard_covers_reference": c["gold"] in base["envelope"]})
    per_case = [{"id": c["id"], "standard": [r[i]["category"] for r in standard],
                 "interleaved": [r[i]["category"] for r in interleaved]} for i, c in enumerate(cases)]
    return {"standard": identical_share(standard), "interleaved": identical_share(interleaved),
            "all_runs": identical_share(standard + interleaved), "per_case": per_case,
            "thorough": {"cases": len(cases), "widened": sum(w["widened"] for w in widened),
                         "widened_and_covers_reference": sum(w["widened"] and w["covers_reference"] for w in widened),
                         "rows": widened}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    cases = compare_cases(select_split(load(), "dev", read_split()))
    res = {**run_meta(), "split": "dev", "runs": a.runs, **repeatability(cases, a.runs)}
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("standard", "interleaved", "all_runs")}, indent=1))
    print("thorough:", {k: v for k, v in res["thorough"].items() if k != "rows"})
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
