r"""
Inter-annotator agreement on feature-level gold labels.

    .\.venv\Scripts\python.exe data_tools\annotator_kappa.py annotator_a.csv annotator_b.csv

Both files use the real-case columns (id plus gold_aphe, gold_washout, gold_capsule,
gold_growth, gold_size_mm, radiologist_category may be present). Rows are matched by id.
Reports Cohen's kappa per feature over the four states, the quadratic-weighted kappa for the
category, and size agreement (within 1 mm, mean absolute difference). Blank cells are skipped.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radsenvelope.evaluation.metrics import KAPPA_LABELS, STATES, cohen_kappa  # noqa: E402

FEATURES = ("aphe", "washout", "capsule", "growth")


def _read(path: Path) -> dict[str, dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return {r["id"].strip(): r for r in csv.DictReader(fh) if (r.get("id") or "").strip()}


def _state(v) -> str:
    return (v or "").strip().lower().replace(" ", "_")


def agreement(a: dict[str, dict], b: dict[str, dict]) -> dict:
    ids = sorted(set(a) & set(b))
    out = {"matched_ids": len(ids), "features": {}}
    for k in FEATURES:
        pairs = [(_state(a[i].get(f"gold_{k}")), _state(b[i].get(f"gold_{k}"))) for i in ids]
        pairs = [(x, y) for x, y in pairs if x in STATES and y in STATES]
        out["features"][k] = {"n": len(pairs), "agreement": round(sum(x == y for x, y in pairs) / len(pairs), 4)
                              if pairs else None,
                              "kappa": cohen_kappa([x for x, _ in pairs], [y for _, y in pairs], STATES)}
    cats = [(a[i].get("radiologist_category", "").strip().upper(), b[i].get("radiologist_category", "").strip().upper())
            for i in ids]
    cats = [(x, y) for x, y in cats if x in KAPPA_LABELS and y in KAPPA_LABELS]
    out["category"] = {"n": len(cats), "weighted_kappa": cohen_kappa([x for x, _ in cats], [y for _, y in cats],
                                                                      KAPPA_LABELS, "quadratic")}
    sizes = []
    for i in ids:
        try:
            sizes.append((float(a[i]["gold_size_mm"]), float(b[i]["gold_size_mm"])))
        except (KeyError, TypeError, ValueError):
            continue
    out["size"] = {"n": len(sizes),
                   "within_1mm": round(sum(abs(x - y) <= 1 for x, y in sizes) / len(sizes), 4) if sizes else None,
                   "mean_abs_diff_mm": round(sum(abs(x - y) for x, y in sizes) / len(sizes), 2) if sizes else None}
    return out


def filled(rows: dict[str, dict]) -> int:
    """Number of rows with at least one feature label."""
    return sum(any(_state(r.get(f"gold_{k}")) in STATES for k in FEATURES) for r in rows.values())


def adjudicate(a: dict[str, dict], b: dict[str, dict]) -> dict[str, dict]:
    """Adjudicated gold: a feature label is kept only where both annotators agree."""
    gold = {}
    for i in sorted(set(a) & set(b)):
        g = {k: _state(a[i].get(f"gold_{k}")) for k in FEATURES
             if _state(a[i].get(f"gold_{k}")) in STATES and _state(a[i].get(f"gold_{k}")) == _state(b[i].get(f"gold_{k}"))}
        if g:
            gold[i] = g
    return gold


def report(a: dict[str, dict], b: dict[str, dict], results: dict | None = None) -> dict:
    """Inter-annotator agreement and extractor F1 against adjudicated gold, or the status if not collected."""
    na, nb = filled(a), filled(b)
    if not na or not nb:
        return {"status": "not yet collected (single reviewer)", "annotator_a_filled": na,
                "annotator_b_filled": nb, "matched_ids": len(set(a) & set(b))}
    out = {"status": "collected", **agreement(a, b)}
    gold = adjudicate(a, b)
    out["adjudicated_cases"] = len(gold)
    if results and gold:
        from radsenvelope.evaluation.metrics import feature_scores
        for system in ("B1", "B2", "Ours"):
            rows = {r["id"]: r.get("features") or {} for r in results["systems"].get(system, {}).get("rows", [])}
            pairs = [(g, rows[i]) for i, g in gold.items() if i in rows]
            if pairs:
                out.setdefault("extractor_f1_vs_adjudicated", {})[system] = feature_scores(pairs, FEATURES)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("annotator_a", type=Path)
    ap.add_argument("annotator_b", type=Path)
    ap.add_argument("--results", type=Path, help="comparison results JSON for extractor F1 against adjudicated gold")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    results = json.loads(a.results.read_text(encoding="utf-8")) if a.results else None
    res = report(_read(a.annotator_a), _read(a.annotator_b), results)
    if a.out:
        a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
