r"""
Leakage-proof dev/test split of the real cases.

    .\.venv\Scripts\python.exe data_tools\split_real.py

Stratified random split by source (radiopaedia / pmc / europepmc) and radiologist category,
seed 2026: 40 % dev, 60 % test. Every case already inspected during development is forced into
dev, with the reason recorded. Writes data\real\split.csv (id, source, category, split,
forced_dev_reason) and prints the sha256 of the sorted test-id list, which goes into the freeze
commit message (tag "eval-freeze").
"""
from __future__ import annotations

import csv
import hashlib
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "real" / "split.csv"
SEED = 2026
DEV_FRACTION = 0.4

# cases the LLM pipeline was run on and errors were analysed during development
FORCED_DEV = {
    "RP001": "evaluated and error-analysed during development (washout misread)",
    "RP002": "evaluated and error-analysed during development (late-arterial APHE misread)",
    "RP003": "evaluated during development (scope-guard synonym fix)",
    "PMC001": "evaluated during development (APHE call depends on call order)",
    "PMC002": "evaluated and error-analysed during development (ultrasound growth misread)",
}
# Europe PMC articles whose text was displayed while the harvester was developed
FORCED_DEV_PMCIDS = {p: "article text shown during harvester development" for p in (
    "PMC13031818", "PMC13110564", "PMC12358762", "PMC11172993", "PMC9053256", "PMC12812238",
    "PMC11436280", "PMC10070055", "PMC9951896", "PMC8122342", "PMC12839964")}


def source_of(case_id: str) -> str:
    if case_id.startswith("EPMC"):
        return "europepmc"
    if case_id.startswith("PMC"):
        return "pmc"
    if case_id.startswith("RP"):
        return "radiopaedia"
    return "other"


def forced_reason(row: dict) -> str:
    if row["id"] in FORCED_DEV:
        return FORCED_DEV[row["id"]]
    m = re.search(r"PMC\d+", row.get("url") or "")
    return FORCED_DEV_PMCIDS.get(m.group(0), "") if m else ""


def make_split(rows: list[dict], seed: int = SEED, dev_fraction: float = DEV_FRACTION) -> list[dict]:
    """rows need id, url, radiologist_category. Deterministic for a given seed and input."""
    from radsenvelope.evaluation.real_cases import normalise
    strata: dict[tuple[str, str], list[dict]] = {}
    for r in sorted(rows, key=lambda r: r["id"]):
        cat = normalise(r.get("radiologist_category", "")) or "unknown"
        strata.setdefault((source_of(r["id"]), cat), []).append(r)
    rng = random.Random(seed)
    out = []
    for key in sorted(strata):
        members = strata[key]
        forced = [r for r in members if forced_reason(r)]
        free = [r for r in members if not forced_reason(r)]
        rng.shuffle(free)
        extra_dev = max(0, round(dev_fraction * len(members)) - len(forced))
        for r in forced:
            out.append({"id": r["id"], "source": key[0], "category": key[1], "split": "dev",
                        "forced_dev_reason": forced_reason(r)})
        for i, r in enumerate(free):
            out.append({"id": r["id"], "source": key[0], "category": key[1],
                        "split": "dev" if i < extra_dev else "test", "forced_dev_reason": ""})
    return sorted(out, key=lambda r: r["id"])


def test_ids_sha256(split_rows: list[dict]) -> str:
    ids = sorted(r["id"] for r in split_rows if r["split"] == "test")
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def main() -> None:
    from radsenvelope.evaluation.real_cases import load
    rows = make_split(load())
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "source", "category", "split", "forced_dev_reason"])
        w.writeheader()
        w.writerows(rows)
    n = {s: sum(r["split"] == s for r in rows) for s in ("dev", "test")}
    print(f"{len(rows)} cases: dev {n['dev']} (forced {sum(bool(r['forced_dev_reason']) for r in rows)}), test {n['test']}")
    print(f"test-id sha256: {test_ids_sha256(rows)}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
