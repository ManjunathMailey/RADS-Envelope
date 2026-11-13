r"""
Evaluation on real, radiologist-written cases.

    python -m radsenvelope.evaluation.real_cases                  # LLM, lexicon fallback
    python -m radsenvelope.evaluation.real_cases --extractor lexicon
    python -m radsenvelope.evaluation.real_cases --compare        # B1 / B2 / B3 / Ours side by side
    python -m radsenvelope.evaluation.real_cases --compare --split dev   # default; test needs RADS_RUN_TEST=1

Dev/test protocol: data/real/split.csv (data_tools/split_real.py) fixes which cases are held out.
--split test is refused unless RADS_RUN_TEST=1, and every test run is appended to
data/real/test_runs.log (time, git commit, prompt hash). Results are written per split.

Input:  data/real/radiopaedia_cases.csv
        columns: id,url,author,license,modality,findings_text,radiologist_category,collected_by,collected_on,notes
        optional feature-level gold: gold_aphe,gold_washout,gold_capsule,gold_growth (present / absent /
        uncertain / not_documented) and gold_size_mm; per-feature F1 is reported where they are filled in.
Output: data/real/results.json (served to the Evaluation view) and data/real/results.csv;
        --compare writes data/real/results.comparison.json.
Rows whose id, findings_text or radiologist_category starts with "TODO" are skipped.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path

from radsenvelope.engine.ruleset import rank
from radsenvelope.pipeline import Settings, analyse_report

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "data" / "real" / "radiopaedia_cases.csv"
OUT_JSON = ROOT / "data" / "real" / "results.json"
OUT_CSV = ROOT / "data" / "real" / "results.csv"
DEFER = {"LR-M", "LR-TIV", "LR-TR"}
_CAT = re.compile(r"^\s*(?:LI-?RADS|LR)?[\s:-]*(?:category\s*)?([1-5]|M|TIV|NC|TR)\b", re.I)


def normalise(text: str) -> str | None:
    m = _CAT.match(text or "")
    return f"LR-{m.group(1).upper()}" if m else None


def _numeric(c: str | None) -> bool:
    return bool(c) and c[-1].isdigit()


def is_todo(row: dict) -> bool:
    return (not (row.get("findings_text") or "").strip()) or any(
        (row.get(k) or "").strip().upper().startswith("TODO") for k in ("id", "findings_text", "radiologist_category"))


def load(path: Path = CASES) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if not is_todo(r)]


def evaluate(rows: list[dict], extractor: str = "auto", samples: int = 1) -> dict:
    out_rows = []
    for row in rows:
        res = analyse_report(row["findings_text"], Settings(extractor=extractor, samples=samples))
        o = res["observations"][0]
        r = o["result"]
        rad = normalise(row.get("radiologist_category", ""))
        ours = r.get("acr_category")
        comparable = _numeric(rad) and ours is not None
        out_rows.append({
            "id": row.get("id"), "url": row.get("url"), "author": row.get("author"),
            "license": row.get("license"), "modality": row.get("modality"),
            "radiologist_category": rad, "status": r["status"], "category": ours,
            "envelope": r.get("envelope"), "decision_critical": bool(r.get("decision_critical")),
            "exact": comparable and ours == rad,
            "within_one": comparable and abs(rank(ours) - rank(rad)) <= 1,
            "in_envelope": comparable and rad in (r.get("envelope") or []),
            "correct_deferral": rad in DEFER and r["status"] == "defer",
            "seconds": res["extractor"].get("seconds"), "extractor": res["extractor"].get("used"),
        })
    comp = [x for x in out_rows if _numeric(x["radiologist_category"]) and x["category"]]
    defer_cases = [x for x in out_rows if x["radiologist_category"] in DEFER]
    secs = [x["seconds"] for x in out_rows if x["seconds"] is not None]
    pct = lambda a, b: round(a / b, 3) if b else None
    summary = {
        "cases": len(out_rows), "compared": len(comp),
        "exact_agreement": pct(sum(x["exact"] for x in comp), len(comp)),
        "within_one": pct(sum(x["within_one"] for x in comp), len(comp)),
        "radiologist_in_envelope": pct(sum(x["in_envelope"] for x in comp), len(comp)),
        "decision_critical": sum(x["decision_critical"] for x in out_rows),
        "correct_deferrals": f"{sum(x['correct_deferral'] for x in defer_cases)}/{len(defer_cases)}",
        "not_assignable": sum(x["status"] == "not_assignable" for x in out_rows),
        "mean_seconds": round(sum(secs) / len(secs), 2) if secs else None,
    }
    from .provenance import run_meta
    return {**run_meta(), "extractor": extractor, "summary": summary, "rows": out_rows}


GOLD_FEATURES = ("aphe", "washout", "capsule", "growth")
OUT_COMPARE = ROOT / "data" / "real" / "results.comparison.json"
_STATES = {"present", "absent", "uncertain", "not_documented"}


def gold_features(row: dict) -> dict:
    """Feature-level gold from the optional gold_* columns (blank = not annotated)."""
    out = {}
    for k in GOLD_FEATURES:
        v = (row.get(f"gold_{k}") or "").strip().lower().replace(" ", "_")
        if v in _STATES:
            out[k] = v
    return out


def gold_size(row: dict) -> float | None:
    try:
        return float((row.get("gold_size_mm") or "").strip())
    except ValueError:
        return None


def source_of(case_id: str) -> str:
    if (case_id or "").startswith("EPMC"):
        return "europepmc"
    if (case_id or "").startswith("PMC"):
        return "pmc"
    if (case_id or "").startswith("RP"):
        return "radiopaedia"
    return "other"


def compare_cases(rows: list[dict]) -> list[dict]:
    return [{"id": r.get("id"), "text": r["findings_text"], "gold": normalise(r.get("radiologist_category", "")),
             "gold_features": gold_features(r), "gold_size_mm": gold_size(r), "source": source_of(r.get("id"))}
            for r in rows]


SPLIT = ROOT / "data" / "real" / "split.csv"
TEST_LOG = ROOT / "data" / "real" / "test_runs.log"


def read_split(path: Path = SPLIT) -> dict[str, str] | None:
    """{id: "dev" | "test"} from split.csv, or None before the split has been made."""
    if not path.exists():
        return None
    with open(path, encoding="utf-8", newline="") as fh:
        return {r["id"]: r["split"] for r in csv.DictReader(fh)}


def select_split(rows: list[dict], which: str, split: dict[str, str] | None) -> list[dict]:
    """Before the split exists every case is a development case (all were inspected)."""
    if which == "all":
        return rows
    if split is None:
        return rows if which == "dev" else []
    return [r for r in rows if split.get(r.get("id")) == which]


def check_test_allowed(which: str, split: dict[str, str] | None, env: dict) -> None:
    """Held-out cases may only be scored deliberately: --split test (or all, once a test set
    exists) needs RADS_RUN_TEST=1. Raises SystemExit otherwise."""
    touches_test = which == "test" or (which == "all" and split is not None and "test" in split.values())
    if not touches_test:
        return
    if split is None:
        raise SystemExit("No test split exists yet (data/real/split.csv is created at the evaluation freeze).")
    if env.get("RADS_RUN_TEST") != "1":
        raise SystemExit("Refusing to score held-out test cases. Set RADS_RUN_TEST=1 to run the final test.")


def log_test_run(which: str, args: dict, path: Path = TEST_LOG) -> dict:
    from .provenance import run_meta
    entry = {**run_meta(), "split": which, "args": args}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extractor", choices=["auto", "llm", "lexicon"], default="auto")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--compare", action="store_true", help="run B1, B2, B3 and Ours side by side")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    a = ap.parse_args()
    split = read_split()
    check_test_allowed(a.split, split, dict(os.environ))
    rows = select_split(load(), a.split, split)
    if not rows:
        print(f"No {a.split} cases found in {CASES} (TODO rows are skipped).")
        return
    if a.split in ("test", "all") and split is not None:
        log_test_run(a.split, vars(a))
    if a.compare:
        from .compare import run, table
        from .provenance import run_meta
        res = run(compare_cases(rows), samples=a.samples)
        out = ROOT / "data" / "real" / f"results.comparison.{a.split}.json"
        out.write_text(json.dumps({**run_meta(), "split": a.split, "split_file": str(SPLIT.name) if split else None,
                                   "cases": len(rows), "case_ids": [r.get("id") for r in rows], "systems": res},
                                  indent=1), encoding="utf-8")
        for t in table(res):
            print(json.dumps(t, ensure_ascii=False))
        print(f"Saved {out}")
        return
    res = evaluate(rows, a.extractor, a.samples)
    res["split"] = a.split
    out_json = ROOT / "data" / "real" / f"results.{a.split}.json"
    out_json.write_text(json.dumps(res, indent=1), encoding="utf-8")
    with open(out_json.with_suffix(".csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(res["rows"][0]))
        w.writeheader()
        for r in res["rows"]:
            w.writerow({**r, "envelope": " ".join(r["envelope"] or [])})
    print(json.dumps(res["summary"], indent=1))


if __name__ == "__main__":
    main()
