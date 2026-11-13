r"""
Real-patient label analysis on WAW-TACE (233 patients, radiologist LI-RADS labels, no feature labels).

    .\.venv\Scripts\python.exe data_tools\wawtace_analysis.py

Uses only the clinical table (data\raw\waw_tace\clinical_data_wawtace_v2_15_07_2024.xlsx) and the
mask-measured sizes (data\real\ct_lesion_sizes.csv):

1. Measurement variability: |largest mask diameter - largest clinical diameter| per patient
   (median, IQR, share within 2 / 5 / 10 mm) and a Bland-Altman summary (bias, SD, 95 % limits).
2. Cut-off proximity: share of lesions whose clinical diameter lies within +/-2 mm, and within
   +/- the median discrepancy, of a LI-RADS size cut-off (10, 20 mm), by the dataset's label.
3. Size-label consistency audit: for each lesion, the categories our engine can reach with the
   size interval (diameter +/- tolerance) and ALL six features unknown. A label outside that set
   is impossible from size alone under v2018 (e.g. LR-5 below 10 mm: ancillary features cannot
   upgrade to LR-5). This is a consistency check, not an error rate of the dataset.
4. Category distribution of the labels.
Writes data\real\wawtace_analysis.json. The .xlsx is read with the standard library.
"""
from __future__ import annotations

import csv
import json
import re
import statistics
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radsenvelope.engine.ruleset import FEATURES, get_ruleset  # noqa: E402
from radsenvelope.pipeline import run_observation  # noqa: E402

CLINICAL = ROOT / "data" / "raw" / "waw_tace" / "clinical_data_wawtace_v2_15_07_2024.xlsx"
SIZES = ROOT / "data" / "real" / "ct_lesion_sizes.csv"
OUT = ROOT / "data" / "real" / "wawtace_analysis.json"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
TOLERANCE_MM = 2.0
ALL_UNKNOWN = {k: "uncertain" for k in FEATURES}


# ---------------- minimal .xlsx reader (first sheet) ----------------
def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        sheet = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n))[0]
        rows = []
        for row in ET.fromstring(z.read(sheet)).find("m:sheetData", NS).findall("m:row", NS):
            cells = {}
            for c in row.findall("m:c", NS):
                v = c.find("m:v", NS)
                if c.get("t") == "s" and v is not None:
                    val = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
                else:
                    val = v.text if v is not None else ""
                cells[_col(c.get("r"))] = val
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    header = [str(h) for h in rows[0]]
    return [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in rows[1:] if any(str(x).strip() for x in r)]


# ---------------- analysis ----------------
def _num(v) -> float | None:
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def label(v) -> str | None:
    s = str(v).strip().upper().removesuffix(".0")
    return f"LR-{s}" if s in ("1", "2", "3", "4", "5", "M") else None


def _q(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def lesions(clinical: list[dict]) -> list[dict]:
    out = []
    for r in clinical:
        for i in (1, 2, 3):
            d, lab = _num(r.get(f"lesion{i}_diameter")), label(r.get(f"lesion{i}_LIRADS"))
            if d is not None and lab:
                out.append({"patient": str(int(float(r["PATPRI"]))), "lesion": i, "diameter_mm": d, "label": lab})
    return out


def variability(size_rows: list[dict]) -> dict:
    per_patient: dict[str, tuple[float, float]] = {}
    for r in size_rows:
        if r["dataset"] != "WAW-TACE" or not r.get("reference_size_mm"):
            continue
        m, ref = float(r["measured_size_mm"]), float(r["reference_size_mm"])
        cur = per_patient.get(r["patient_id"])
        per_patient[r["patient_id"]] = (max(m, cur[0]) if cur else m, ref)
    diffs = [m - ref for m, ref in per_patient.values()]
    absd = [abs(d) for d in diffs]
    bias, sd = statistics.mean(diffs), statistics.stdev(diffs)
    share = lambda t: round(sum(a <= t for a in absd) / len(absd), 4)
    return {"patients": len(diffs), "median_abs_diff_mm": round(statistics.median(absd), 2),
            "iqr_abs_diff_mm": [round(_q(absd, 0.25), 2), round(_q(absd, 0.75), 2)],
            "within_2mm": share(2), "within_5mm": share(5), "within_10mm": share(10),
            "bland_altman": {"bias_mm": round(bias, 2), "sd_mm": round(sd, 2),
                             "limits_of_agreement_mm": [round(bias - 1.96 * sd, 2), round(bias + 1.96 * sd, 2)],
                             "definition": "difference = largest mask diameter - largest clinical diameter (mm)"}}


def cutoff_proximity(les: list[dict], margins: dict[str, float]) -> dict:
    cuts = get_ruleset().cutoffs
    out = {}
    for name, m in margins.items():
        near = [x for x in les if any(abs(x["diameter_mm"] - c) <= m for c in cuts)]
        by_label = {}
        for lab in sorted({x["label"] for x in les}):
            group = [x for x in les if x["label"] == lab]
            k = sum(any(abs(x["diameter_mm"] - c) <= m for c in cuts) for x in group)
            by_label[lab] = {"near": k, "lesions": len(group), "share": round(k / len(group), 4)}
        out[name] = {"margin_mm": round(m, 2), "near": len(near), "lesions": len(les),
                     "share": round(len(near) / len(les), 4), "by_label": by_label}
    return out


def reachable(diameter: float, tolerance: float = TOLERANCE_MM) -> list[str]:
    return run_observation("x", ALL_UNKNOWN, diameter, tolerance, True, [])["envelope"]


def consistency(les: list[dict], tolerance: float = TOLERANCE_MM) -> dict:
    flagged, assessable, out_of_scope = [], 0, 0
    for x in les:
        if x["label"] == "LR-M":
            out_of_scope += 1
            continue
        assessable += 1
        env = reachable(x["diameter_mm"], tolerance)
        if x["label"] not in env:
            flagged.append({**x, "reachable_with_size_alone": env})
    return {"tolerance_mm": tolerance, "assessable_lesions": assessable, "lr_m_not_assessed": out_of_scope,
            "flagged": len(flagged), "flagged_share": round(len(flagged) / assessable, 4) if assessable else None,
            "flagged_cases": flagged,
            "rule": "label not reachable by the v2018 table for the size interval with every feature unknown"}


def size_by_label(les: list[dict]) -> dict:
    out = {}
    for lab in sorted({x["label"] for x in les}):
        ds = sorted(x["diameter_mm"] for x in les if x["label"] == lab)
        out[lab] = {"n": len(ds), "min_mm": ds[0], "median_mm": statistics.median(ds),
                    "below_10mm": sum(d < 10 for d in ds), "below_20mm": sum(d < 20 for d in ds)}
    return out


def distribution(les: list[dict], clinical: list[dict]) -> dict:
    count = lambda xs: {k: xs.count(k) for k in sorted(set(xs))}
    first = [label(r.get("lesion1_LIRADS")) for r in clinical if label(r.get("lesion1_LIRADS"))]
    return {"all_lesions": count([x["label"] for x in les]), "lesion1_per_patient": count(first),
            "lesions": len(les), "patients": len(clinical)}


def analyse(clinical: list[dict], size_rows: list[dict]) -> dict:
    les = lesions(clinical)
    var = variability(size_rows)
    return {
        "source": "WAW-TACE (Zenodo 10.5281/zenodo.12741586, CC BY 4.0): clinical table + mask-measured sizes",
        "measurement_variability": var,
        "cutoff_proximity": cutoff_proximity(les, {"within_2mm": 2.0, "within_median_discrepancy": var["median_abs_diff_mm"]}),
        "size_label_consistency": consistency(les, TOLERANCE_MM),
        "size_label_consistency_exact": consistency(les, 0.0),
        "size_label_consistency_median_discrepancy": consistency(les, var["median_abs_diff_mm"]),
        "label_distribution": distribution(les, clinical),
        "diameter_by_label": size_by_label(les),
        "notes": ["No feature labels exist in WAW-TACE; no LI-RADS label is derived here.",
                  "Phase codes of the masks are unverified against the dataset paper; the variability uses the "
                  "largest mask over all phases against the dataset's portal-phase clinical diameter."],
    }


def main() -> None:
    clinical = read_xlsx(CLINICAL)
    with open(SIZES, encoding="utf-8", newline="") as fh:
        size_rows = list(csv.DictReader(fh))
    res = analyse(clinical, size_rows)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    v, c = res["measurement_variability"], res["size_label_consistency"]
    print(json.dumps({"variability": {k: v[k] for k in ("patients", "median_abs_diff_mm", "iqr_abs_diff_mm",
                                                         "within_2mm", "within_5mm", "within_10mm")},
                      "bland_altman": v["bland_altman"],
                      "cutoff": {k: {kk: vv for kk, vv in x.items() if kk != "by_label"} for k, x in res["cutoff_proximity"].items()},
                      "consistency": {k: c[k] for k in ("assessable_lesions", "lr_m_not_assessed", "flagged", "flagged_share")},
                      "distribution": res["label_distribution"]}, indent=1))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
