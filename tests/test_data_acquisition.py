"""Data acquisition tooling: size guard, manifest digests and verification, mask geometry, NRRD reading.
Geometry/NRRD tests need numpy (installed in .venv-data) and are skipped without it."""
import csv
import gzip
import importlib.util
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "data_tools"


def _load(name):
    import sys
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_download_refuses_files_over_5_gb(tmp_path):
    http = _load("fetch_http")
    with pytest.raises(http.TooLarge):
        http.download("https://example.invalid/x.zip", tmp_path / "x.zip", size=6 * 1024 ** 3)
    assert not (tmp_path / "x.zip").exists()


def test_checksum_and_provenance(tmp_path):
    http = _load("fetch_http")
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    assert http._check(f, "md5:5d41402abc4b2a76b9719d911017c592")
    http.write_provenance(tmp_path, [{"file": "a.txt", "license": "cc-by-4.0"}], {"name": "demo"})
    http.write_provenance(tmp_path, [{"file": "a.txt", "notes": "n"}], {"doi": "10/x"})
    import json
    prov = json.loads((tmp_path / "_provenance.json").read_text())
    assert prov["files"]["a.txt"] == {"file": "a.txt", "license": "cc-by-4.0", "notes": "n"}
    assert prov["source"] == {"name": "demo", "doi": "10/x"}


def test_manifest_digest_and_verify(tmp_path):
    bm, vm = _load("build_manifest"), _load("verify_manifest")
    d = tmp_path / "series"
    d.mkdir()
    (d / "1.dcm").write_bytes(b"one")
    (d / "2.dcm").write_bytes(b"two")
    f = tmp_path / "table.csv"
    f.write_text("a,b\n1,2\n")
    manifest = tmp_path / "manifest.csv"
    with open(manifest, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=bm.COLUMNS)
        w.writeheader()
        w.writerow({"source": "s", "sha256": bm.dir_sha256(d)[0], "local_path": "series"})
        w.writerow({"source": "s", "sha256": bm.file_sha256(f), "local_path": "table.csv"})
        w.writerow({"source": "AMPLIFAI", "notes": "requested / pending"})          # status row: skipped
    assert vm.verify(manifest, tmp_path) == {"verified": 2, "missing": [], "changed": []}
    (d / "2.dcm").write_bytes(b"tampered")
    f.unlink()
    assert vm.verify(manifest, tmp_path) == {"verified": 0, "missing": ["table.csv"], "changed": ["series"]}


def test_status_rows_cover_restricted_sources():
    bm = _load("build_manifest")
    names = {r["source"]: r["notes"] for r in bm.STATUS_ROWS}
    for s in ("AMPLIFAI", "MIMIC-IV-Note", "Ramaiah hospital reports"):
        assert names[s].startswith("requested / pending")


# ---------------- geometry and NRRD (numpy) ----------------
def test_max_axial_diameter_of_square_and_largest_region():
    np = pytest.importorskip("numpy")
    ct = _load("ct_lesions")
    m = np.zeros((3, 40, 40), bool)
    m[1, 5:15, 5:15] = True                       # 10 x 10 pixels, centres 9 apart on each axis
    m[2, 30:33, 30:33] = True                     # a smaller second region
    best = ct.largest_axial(m, (0.5, 0.5))
    assert best["slice"] == 1 and best["mm"] == pytest.approx(0.5 * 9 * 2 ** 0.5, abs=1e-6)
    assert best["area_mm2"] == pytest.approx(100 * 0.25)
    assert len(ct.components_2d(m[1] | m[2])) == 2
    assert ct.largest_axial(np.zeros((2, 5, 5), bool), (1, 1)) is None


def test_read_nrrd_gzip_with_spacing():
    np = pytest.importorskip("numpy")
    ct = _load("ct_lesions")
    arr = np.zeros((4, 3, 2), dtype="<i2")         # (z, y, x)
    arr[2, 1, 1] = 1
    header = ("NRRD0004\ntype: short\ndimension: 3\nspace: left-posterior-superior\nsizes: 2 3 4\n"
              "space directions: (0.7,0,0) (0,-0.7,0) (0,0,2.5)\nendian: little\nencoding: gzip\n\n").encode()
    data, h = ct.read_nrrd(header + gzip.compress(arr.tobytes()))
    assert data.shape == (4, 3, 2) and data[2, 1, 1] == 1 and data.sum() == 1
    assert h["spacing_xyz"] == pytest.approx([0.7, 0.7, 2.5])
