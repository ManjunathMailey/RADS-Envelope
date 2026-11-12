r"""
Re-check the sha256 of every downloaded file listed in data\manifest.csv.

    .\.venv\Scripts\python.exe data_tools\verify_manifest.py

Rows without a local_path (restricted or not-downloaded sources) are skipped. Directories are
checked with the same digest build_manifest.py used. Exit code 1 if anything is missing or changed.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_manifest import OUT, ROOT, dir_sha256, file_sha256  # noqa: E402


def verify(manifest: Path = OUT, root: Path = ROOT) -> dict:
    ok, missing, changed = 0, [], []
    with open(manifest, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if not r.get("local_path") or not r.get("sha256"):
                continue
            p = root / r["local_path"]
            if not p.exists():
                missing.append(r["local_path"])
                continue
            digest = dir_sha256(p)[0] if p.is_dir() else file_sha256(p)
            if digest == r["sha256"]:
                ok += 1
            else:
                changed.append(r["local_path"])
    return {"verified": ok, "missing": missing, "changed": changed}


def main() -> None:
    res = verify()
    print(f"verified {res['verified']}, missing {len(res['missing'])}, changed {len(res['changed'])}")
    for k in ("missing", "changed"):
        for p in res[k][:20]:
            print(f"  {k}: {p}")
    sys.exit(1 if res["missing"] or res["changed"] else 0)


if __name__ == "__main__":
    main()
