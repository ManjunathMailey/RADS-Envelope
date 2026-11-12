r"""
Build data\manifest.csv: provenance for every downloaded file and harvested article.

    .\.venv\Scripts\python.exe data_tools\build_manifest.py

Columns: source, url_or_doi, license, retrieved_at, sha256, size_bytes, n_records, notes,
local_path (relative to the repository). Rows come from each source's _provenance.json, from the
Europe PMC harvest (one row per article with full text) and from fixed status rows for sources
that are restricted or not downloaded. A DICOM series directory is one row whose sha256 is the
digest of its files' sorted (name, sha256) list; verify_manifest.py recomputes it the same way.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "manifest.csv"
COLUMNS = ["source", "url_or_doi", "license", "retrieved_at", "sha256", "size_bytes", "n_records", "notes", "local_path"]

STATUS_ROWS = [
    {"source": "AMPLIFAI", "url_or_doi": "https://huggingface.co/datasets/UM-IHC-CA2i/AMPLIFAI",
     "license": "gated (organisers' terms)", "notes": "requested / pending: access requested from the organisers; "
     "not accessed. Unofficial mirrors are not used."},
    {"source": "MIMIC-IV-Note", "url_or_doi": "https://physionet.org/content/mimic-iv-note/",
     "license": "PhysioNet Credentialed Health Data License", "notes": "requested / pending: credentialing"},
    {"source": "Ramaiah hospital reports", "url_or_doi": "via project guide",
     "license": "institutional (ethics approval required)", "notes": "requested / pending: through the project guide"},
    {"source": "PLC-CECT", "url_or_doi": "https://doi.org/10.57760/sciencedb.12207", "license": "CC BY 4.0",
     "size_bytes": 42051498834, "n_records": "", "notes": "not downloaded: DataCite lists 2 files, 42.05 GB in total; "
     "the Science Data Bank file API answered 'permission no access', so file listing needs the website; "
     "needs go before any download"},
]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_sha256(path: Path) -> tuple[str, int]:
    """Digest of a directory: sha256 over sorted 'relative_name sha256' lines. Returns (digest, total bytes)."""
    lines, size = [], 0
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        lines.append(f"{f.relative_to(path).as_posix()} {file_sha256(f)}")
        size += f.stat().st_size
    return hashlib.sha256("\n".join(lines).encode()).hexdigest(), size


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def provenance_rows() -> list[dict]:
    rows = []
    for prov_file in sorted(RAW.glob("*/_provenance.json")):
        prov = json.loads(prov_file.read_text(encoding="utf-8"))
        src_dir = prov_file.parent
        for name, e in prov["files"].items():
            p = src_dir / name
            if not p.exists():
                continue
            digest, size = dir_sha256(p) if p.is_dir() else (file_sha256(p), p.stat().st_size)
            notes = e.get("notes", "") + ("; sha256 over sorted per-file digests" if p.is_dir() else "")
            if e.get("source_checksum"):
                notes += f"; source checksum {e['source_checksum']} verified at download"
            rows.append({"source": prov["source"].get("name", src_dir.name), "url_or_doi": e.get("url_or_doi", ""),
                         "license": e.get("license", ""), "retrieved_at": e.get("retrieved_at", ""), "sha256": digest,
                         "size_bytes": size, "n_records": e.get("n_records", ""), "notes": notes, "local_path": _rel(p)})
        not_taken = {k: v for k, v in (prov["source"].get("all_files") or {}).items() if k not in prov["files"]}
        for k, size in not_taken.items():
            rows.append({"source": prov["source"].get("name", src_dir.name), "url_or_doi": prov["source"].get("doi", ""),
                         "license": prov["source"].get("license", ""), "size_bytes": size,
                         "notes": f"not downloaded: {k}" + (" (over 5 GB; needs go)" if size > 5 * 1024 ** 3 else "")})
    return rows


def europepmc_rows() -> list[dict]:
    base = RAW / "europepmc"
    if not (base / "articles.json").exists():
        return []
    per_article = {}
    if (base / "candidates_per_article.json").exists():
        per_article = json.loads((base / "candidates_per_article.json").read_text(encoding="utf-8"))
    rows = []
    for a in json.loads((base / "articles.json").read_text(encoding="utf-8")):
        p = base / "xml" / f"{a.get('pmcid')}.xml"
        if not a.get("fulltext") or not p.exists():
            continue
        rows.append({"source": "Europe PMC", "url_or_doi": f"https://europepmc.org/article/PMC/{a['pmcid']}"
                     + (f" (doi:{a['doi']})" if a.get("doi") else ""), "license": a.get("license", "").upper(),
                     "retrieved_at": a.get("retrieved_at", ""), "sha256": file_sha256(p), "size_bytes": p.stat().st_size,
                     "n_records": per_article.get(a["pmcid"], 0),
                     "notes": f"full-text JATS XML; queries: {', '.join(a.get('queries') or ['q1_case_reports'])}; "
                              f"n_records = candidate rows extracted", "local_path": _rel(p)})
    return rows


def main() -> None:
    rows = europepmc_rows() + provenance_rows() + STATUS_ROWS
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in COLUMNS} for r in rows)
    by_source: dict[str, list[int]] = {}
    for r in rows:
        s = by_source.setdefault(r["source"], [0, 0])
        if r.get("local_path"):
            s[0] += 1
            s[1] += int(r.get("size_bytes") or 0)
    print(json.dumps({k: {"files": v[0], "MB": round(v[1] / 1024 ** 2, 1)} for k, v in by_source.items()}, indent=1))
    print(f"{len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
