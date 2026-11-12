r"""
Evaluation on real, radiologist-written cases.

    python -m radsenvelope.evaluation.real_cases                  # LLM, lexicon fallback
    python -m radsenvelope.evaluation.real_cases --extractor lexicon

Input:  data/real/radiopaedia_cases.csv
        columns: id,url,author,license,modality,findings_text,radiologist_category,collected_by,collected_on,notes
Output: data/real/results.json (served to the Evaluation view) and data/real/results.csv
Rows whose id, findings_text or radiologist_category starts with "TODO" are skipped.
"""
from __future__ import annotations

import argparse
import csv
import json
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
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "extractor": extractor,
            "summary": summary, "rows": out_rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extractor", choices=["auto", "llm", "lexicon"], default="auto")
    ap.add_argument("--samples", type=int, default=1)
    a = ap.parse_args()
    rows = load()
    if not rows:
        print(f"No cases found in {CASES} (TODO rows are skipped).")
        return
    res = evaluate(rows, a.extractor, a.samples)
    OUT_JSON.write_text(json.dumps(res, indent=1), encoding="utf-8")
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(res["rows"][0]))
        w.writeheader()
        for r in res["rows"]:
            w.writerow({**r, "envelope": " ".join(r["envelope"] or [])})
    print(json.dumps(res["summary"], indent=1))


if __name__ == "__main__":
    main()
