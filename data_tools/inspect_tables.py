r"""
Inspect clinical / metadata tables and flag columns that may relate to LI-RADS.

    .\.venv-data\Scripts\python.exe data_tools\inspect_tables.py FILE [FILE ...] [--json OUT]

Reads .csv and .xlsx (every sheet). For each table: rows, columns, and for columns whose name
matches a LI-RADS-related term (size, enhancement, washout, capsule, LI-RADS, diagnosis, BCLC,
AFP, cirrhosis, ...) the number of non-empty values and a few distinct example values.
It reports what is there; it never derives a LI-RADS label.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

TERMS = {
    "lirads": r"li-?rads|\blr\b",
    "size": r"size|diam|\bmm\b|\bcm\b|volume|largest",
    "enhancement": r"enhanc|aphe|arterial|hypervasc",
    "washout": r"wash",
    "capsule": r"capsul",
    "growth": r"growth",
    "diagnosis": r"diagn|histolog|patholog|grade|edmondson|\bhcc\b",
    "bclc": r"bclc|barcelona",
    "afp": r"\bafp\b|alpha.?feto",
    "cirrhosis": r"cirrho|child|meld|fibros|hepatitis|hbv|hcv|etiolog|aetiolog",
    "treatment": r"tace|response|mrecist|recist|survival|\bos\b|\bttp\b",
    "lesions": r"lesion|nodul|tumou?r|focal|number|multi",
}


def _flags(name: str) -> list[str]:
    return [k for k, rx in TERMS.items() if re.search(rx, str(name), re.I)]


def inspect_frame(df: pd.DataFrame, label: str) -> dict:
    cols = []
    for c in df.columns:
        flags = _flags(c)
        s = df[c].dropna()
        cols.append({"column": str(c), "flags": flags, "non_empty": int(s.size),
                     "examples": [str(v)[:40] for v in s.astype(str).unique()[:5]] if flags else []})
    return {"table": label, "rows": int(len(df)), "n_columns": len(df.columns), "columns": cols}


def inspect(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        return [inspect_frame(pd.read_csv(path, low_memory=False), path.name)]
    sheets = pd.read_excel(path, sheet_name=None)
    return [inspect_frame(df, f"{path.name}[{name}]") for name, df in sheets.items()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    out = [t for f in a.files for t in inspect(f)]
    for t in out:
        print(f"\n== {t['table']}: {t['rows']} rows x {t['n_columns']} columns")
        print("   all columns:", ", ".join(c["column"] for c in t["columns"]))
        for c in t["columns"]:
            if c["flags"]:
                print(f"   [{'/'.join(c['flags'])}] {c['column']} (n={c['non_empty']}): {c['examples']}")
    if a.json:
        a.json.write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
