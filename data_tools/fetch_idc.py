r"""
NCI Imaging Data Commons (IDC) access through the official idc-index client.

    .\.venv-data\Scripts\python.exe data_tools\fetch_idc.py metadata hcc_tace_seg
    .\.venv-data\Scripts\python.exe data_tools\fetch_idc.py metadata tcga_lihc
    .\.venv-data\Scripts\python.exe data_tools\fetch_idc.py download hcc_tace_seg --patients 10

metadata  writes the collection's series list and its IDC clinical table(s) as CSV under
          data\raw\<collection>\ (no images).
download  fetches, for N patients, the study that carries the expert tumour segmentation
          ("Segmentation" SEG, the pre-treatment CT) together with every CT series of that
          study. Sizes are checked first: any single series over 5 GB, or a total that would
          exceed the 25 GB budget, stops the run. Downloads are resumable (s5cmd skips files
          already present).
Every file is recorded in data\raw\<collection>\_provenance.json (license per series from IDC).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
from idc_index import IDCClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_http import write_provenance  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
SINGLE_LIMIT_MB = 5 * 1024
BUDGET_MB = 25 * 1024
EXPERT_SEG = "Segmentation"


def _client() -> IDCClient:
    c = IDCClient()
    c.fetch_index("clinical_index")
    return c


def metadata(collection: str) -> dict:
    c = _client()
    out = RAW / collection
    out.mkdir(parents=True, exist_ok=True)
    s = c.index[c.index["collection_id"] == collection]
    cols = ["PatientID", "StudyInstanceUID", "StudyDate", "SeriesInstanceUID", "Modality", "SeriesDescription",
            "SeriesNumber", "instanceCount", "series_size_MB", "license_short_name", "source_DOI"]
    s[cols].sort_values(["PatientID", "StudyDate", "SeriesNumber"]).to_csv(out / f"{collection}_series.csv", index=False)
    entries = [{"file": f"{collection}_series.csv", "url_or_doi": f"IDC {c.get_idc_version()} index; "
                + ", ".join(sorted(s["source_DOI"].dropna().unique())),
                "license": "; ".join(sorted(s["license_short_name"].unique())),
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_records": int(len(s)),
                "notes": "series list (metadata only)"}]
    tables = c.clinical_index[c.clinical_index["collection_id"] == collection]["short_table_name"].unique()
    for t in tables:
        df = c.get_clinical_table(t)
        name = f"clinical_{t}.csv"
        df.to_csv(out / name, index=False)
        entries.append({"file": name, "url_or_doi": f"IDC {c.get_idc_version()} clinical table {t}",
                        "license": "; ".join(sorted(s["license_short_name"].unique())),
                        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_records": int(len(df)),
                        "notes": "IDC clinical data"})
    write_provenance(out, entries, {"name": collection, "idc_version": c.get_idc_version(),
                                    "doi": sorted(s["source_DOI"].dropna().unique())})
    return {"collection": collection, "patients": int(s["PatientID"].nunique()), "series": int(len(s)),
            "size_GB": round(s["series_size_MB"].sum() / 1024, 1), "modalities": s["Modality"].value_counts().to_dict(),
            "licenses": s["license_short_name"].value_counts().to_dict(), "clinical_tables": list(tables)}


def select_pretreatment(index: pd.DataFrame, collection: str, n: int) -> pd.DataFrame:
    """Series to download: per patient, the study holding the expert SEG plus all its CT series."""
    s = index[index["collection_id"] == collection]
    segs = s[(s["Modality"] == "SEG") & (s["SeriesDescription"] == EXPERT_SEG)]
    studies = segs.sort_values("PatientID").drop_duplicates("PatientID").head(n)["StudyInstanceUID"]
    sel = s[s["StudyInstanceUID"].isin(studies) & ((s["Modality"] == "CT") | (s["SeriesDescription"] == EXPERT_SEG))]
    return sel


def download(collection: str, n: int, dry_run: bool = False) -> dict:
    c = _client()
    sel = select_pretreatment(c.index, collection, n)
    total, biggest = sel["series_size_MB"].sum(), sel["series_size_MB"].max()
    used = sum(f.stat().st_size for f in RAW.rglob("*") if f.is_file()) / 1024 ** 2
    plan = {"patients": int(sel["PatientID"].nunique()), "series": int(len(sel)),
            "total_GB": round(total / 1024, 2), "largest_series_MB": round(float(biggest), 1),
            "raw_used_GB_before": round(used / 1024, 2)}
    if biggest > SINGLE_LIMIT_MB:
        return {**plan, "stopped": "a single series exceeds 5 GB; needs approval"}
    if used + total > BUDGET_MB:
        return {**plan, "stopped": "would exceed the 25 GB budget"}
    if dry_run:
        return {**plan, "dry_run": True}
    out = RAW / collection / "dicom"
    out.mkdir(parents=True, exist_ok=True)
    c.download_from_selection(downloadDir=str(out), seriesInstanceUID=list(sel["SeriesInstanceUID"]),
                              dirTemplate="%PatientID/%StudyInstanceUID/%Modality_%SeriesInstanceUID")
    sel.to_csv(RAW / collection / "downloaded_series.csv", index=False)
    entries = []
    for _, r in sel.iterrows():
        d = out / r["PatientID"] / r["StudyInstanceUID"] / f"{r['Modality']}_{r['SeriesInstanceUID']}"
        entries.append({"file": str(d.relative_to(RAW / collection)).replace("\\", "/"), "is_dir": True,
                        "url_or_doi": f"{r['source_DOI']}; SeriesInstanceUID {r['SeriesInstanceUID']}",
                        "license": r["license_short_name"], "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "n_records": int(r["instanceCount"]),
                        "notes": f"{r['PatientID']} {r['Modality']} '{r['SeriesDescription']}'"})
    write_provenance(RAW / collection, entries, {"name": collection, "idc_version": c.get_idc_version()})
    return {**plan, "downloaded_to": str(out)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("metadata")
    m.add_argument("collection")
    d = sub.add_parser("download")
    d.add_argument("collection")
    d.add_argument("--patients", type=int, default=10)
    d.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    res = metadata(a.collection) if a.cmd == "metadata" else download(a.collection, a.patients, a.dry_run)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
