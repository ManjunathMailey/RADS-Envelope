r"""
Append reviewed Europe PMC candidates to the real-case file.

    .\.venv\Scripts\python.exe data_tools\merge_reviewed.py [--dry-run]

Rows of data\real\candidates_europepmc.csv whose review_status is "accept" are appended to
data\real\radiopaedia_cases.csv as EPMC001, EPMC002, ... (numbering continues after the highest
existing EPMC id). A row whose URL and findings text already appear in the target is skipped.
Only the target file's columns are written.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data" / "real" / "candidates_europepmc.csv"
TARGET = ROOT / "data" / "real" / "radiopaedia_cases.csv"


def _key(row: dict) -> tuple[str, str]:
    return (row.get("url") or "").strip().lower(), " ".join((row.get("findings_text") or "").split()).lower()


def merge(candidates: Path = CANDIDATES, target: Path = TARGET, dry_run: bool = False) -> dict:
    with open(target, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header, existing = list(reader.fieldnames or []), list(reader)
    with open(candidates, encoding="utf-8-sig", newline="") as fh:
        cands = list(csv.DictReader(fh))
    seen = {_key(r) for r in existing}
    numbers = [int(m.group(1)) for r in existing if (m := re.fullmatch(r"EPMC(\d+)", r.get("id") or ""))]
    nxt = max(numbers, default=0) + 1
    added, skipped = [], 0
    for c in cands:
        if (c.get("review_status") or "").strip().lower() != "accept":
            continue
        if _key(c) in seen:
            skipped += 1
            continue
        row = {k: c.get(k, "") for k in header}
        row["id"] = f"EPMC{nxt:03d}"
        nxt += 1
        seen.add(_key(c))
        added.append(row)
    if added and not dry_run:
        with open(target, "a", encoding="utf-8", newline="") as fh:
            csv.DictWriter(fh, fieldnames=header).writerows(added)
    return {"accepted_added": len(added), "duplicates_skipped": skipped, "ids": [r["id"] for r in added],
            "dry_run": dry_run}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    print(merge(dry_run=ap.parse_args().dry_run))


if __name__ == "__main__":
    main()
