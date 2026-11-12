r"""
Polite, resumable HTTP downloads with provenance, shared by the open-data fetchers.

Rules enforced here: at most 3 requests per second, exponential backoff on 429/5xx and network
errors, resumable downloads (.part file + HTTP Range), checksum verification when the source
publishes one, and a hard stop for any single file over 5 GB unless --allow-large is given.
Each source folder gets a _provenance.json describing every file (url, license, retrieved_at,
checksum, n_records, notes) that data_tools\build_manifest.py turns into data\manifest.csv.

    .\.venv\Scripts\python.exe data_tools\fetch_http.py zenodo 12741586 --source waw_tace ^
        --files clinical_data_wawtace_v2_15_07_2024.xlsx ct_hcc_metadata_v2.csv ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
USER_AGENT = "rads-envelope-data-tools/1.0 (research prototype)"
MIN_INTERVAL = 1 / 3
LARGE = 5 * 1024 ** 3
_last = [0.0]


class TooLarge(RuntimeError):
    pass


def _throttle() -> None:
    wait = MIN_INTERVAL - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()


def get_json(url: str, cache: Path | None = None, attempts: int = 5):
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    for attempt in range(attempts):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(data, indent=1), encoding="utf-8")
            return data
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
        except urllib.error.URLError:
            if attempt == attempts - 1:
                raise
        time.sleep(2 ** attempt)


def file_hash(path: Path, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, size: int | None = None, checksum: str | None = None,
             allow_large: bool = False, attempts: int = 6) -> Path:
    """Resumable download. checksum like 'md5:abc...' is verified when given."""
    if size and size > LARGE and not allow_large:
        raise TooLarge(f"{dest.name} is {size / 1024 ** 3:.1f} GB (> 5 GB); needs explicit approval (--allow-large)")
    if dest.exists() and (size is None or dest.stat().st_size == size):
        if not checksum or _check(dest, checksum):
            return dest
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(attempts):
        done = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if done:
            headers["Range"] = f"bytes={done}-"
        _throttle()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as r, open(part, "ab" if done and r.status == 206 else "wb") as fh:
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    fh.write(chunk)
            break
        except urllib.error.HTTPError as e:
            if e.code == 416:                      # already complete
                break
            if e.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(2 ** attempt)
    if size is not None and part.stat().st_size != size:
        raise RuntimeError(f"{dest.name}: got {part.stat().st_size} bytes, expected {size}")
    if checksum and not _check(part, checksum):
        raise RuntimeError(f"{dest.name}: checksum mismatch ({checksum})")
    part.replace(dest)
    return dest


def _check(path: Path, checksum: str) -> bool:
    algo, _, value = checksum.partition(":")
    return file_hash(path, algo) == value.lower()


def write_provenance(source_dir: Path, entries: list[dict], source_meta: dict) -> None:
    """Merge entries (keyed by local file name) into <source_dir>/_provenance.json."""
    path = source_dir / "_provenance.json"
    prov = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"source": source_meta, "files": {}}
    prov["source"].update(source_meta)
    for e in entries:
        prov["files"][e["file"]] = {**prov["files"].get(e["file"], {}), **e}
    path.write_text(json.dumps(prov, indent=1), encoding="utf-8")


def zenodo(record: str, source: str, files: list[str], allow_large: bool = False) -> dict:
    meta = get_json(f"https://zenodo.org/api/records/{record}", RAW / source / "_zenodo_record.json")
    lic = (meta["metadata"].get("license") or {}).get("id", "")
    listing = {f["key"]: f for f in meta["files"]}
    entries, skipped = [], {}
    for name in files:
        f = listing.get(name)
        if f is None:
            skipped[name] = "not in record"
            continue
        try:
            download(f["links"]["self"], RAW / source / name, f["size"], f["checksum"], allow_large)
        except TooLarge as e:
            skipped[name] = str(e)
            continue
        entries.append({"file": name, "url_or_doi": f["links"]["self"], "license": lic,
                        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "source_checksum": f["checksum"],
                        "notes": f"Zenodo record {record} ({meta.get('doi', '')})"})
    write_provenance(RAW / source, entries, {"name": source, "doi": meta.get("doi"), "license": lic,
                                             "title": meta["metadata"].get("title"),
                                             "all_files": {k: v["size"] for k, v in listing.items()}})
    return {"downloaded": [e["file"] for e in entries], "skipped": skipped, "license": lic}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    z = sub.add_parser("zenodo")
    z.add_argument("record")
    z.add_argument("--source", required=True)
    z.add_argument("--files", nargs="+", required=True)
    z.add_argument("--allow-large", action="store_true")
    a = ap.parse_args()
    if a.cmd == "zenodo":
        print(json.dumps(zenodo(a.record, a.source, a.files, a.allow_large), indent=1))
    sys.exit(0)


if __name__ == "__main__":
    main()
