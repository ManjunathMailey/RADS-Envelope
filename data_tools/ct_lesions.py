r"""
Lesion size from real tumour masks, and CT previews.

    .\.venv-data\Scripts\python.exe data_tools\ct_lesions.py sizes
    .\.venv-data\Scripts\python.exe data_tools\ct_lesions.py preview --patients HCC_002 HCC_003 HCC_004

sizes    writes data\real\ct_lesion_sizes.csv: the maximum in-plane (axial) diameter in mm of the
         largest connected tumour region in each mask, from
           * WAW-TACE 3D Slicer .seg.nrrd tumour masks (one file per tumour and phase), next to the
             dataset's own "maximal diameter in axial plane (portal phase)" for comparison;
           * HCC-TACE-Seg DICOM SEG, segment "Mass", on the pre-treatment multiphase CT.
         Diameter = largest distance between pixel centres of the region's convex hull on one slice.
preview  writes docs\figures\ct_preview_<patient>.png for HCC-TACE-Seg patients: the slice with the
         largest tumour area, both contrast phases side by side, the mask outline and the diameter.
Phase labels come from the images: each acquisition's mean attenuation inside the SEG's
"Abdominal aorta" segment; the brighter one is called arterial, the other portal venous (if the
difference is under 30 HU the phases are reported as unresolved). No LI-RADS label is derived.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT_CSV = ROOT / "data" / "real" / "ct_lesion_sizes.csv"
FIG_DIR = ROOT / "docs" / "figures"
WAW_MASKS = RAW / "waw_tace" / "tumor_masks_wawtace_v1_08_05_2024.zip"
WAW_CLINICAL = RAW / "waw_tace" / "clinical_data_wawtace_v2_15_07_2024.xlsx"
HCC_DICOM = RAW / "hcc_tace_seg" / "dicom"
MIN_PHASE_GAP_HU = 30.0
COLUMNS = ["dataset", "patient_id", "mask", "phase", "segment", "measured_size_mm", "slice_z_mm", "region_area_mm2",
           "reference_size_mm", "reference_source", "notes"]


# ---------------- geometry ----------------
def components_2d(mask: np.ndarray) -> list[np.ndarray]:
    """4-connected components of a 2D boolean mask, as arrays of (row, col)."""
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for r0, c0 in zip(*np.nonzero(mask)):
        if seen[r0, c0]:
            continue
        stack, pts = [(r0, c0)], []
        seen[r0, c0] = True
        while stack:
            r, c = stack.pop()
            pts.append((r, c))
            for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= rr < mask.shape[0] and 0 <= cc < mask.shape[1] and mask[rr, cc] and not seen[rr, cc]:
                    seen[rr, cc] = True
                    stack.append((rr, cc))
        comps.append(np.array(pts))
    return comps


def _cross(o, a, b) -> float:
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


def _hull(points: np.ndarray) -> np.ndarray:
    """Monotone-chain convex hull of 2D points (float array, N x 2)."""
    pts = np.unique(points, axis=0)
    if len(pts) <= 2:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and _cross(h[-2], h[-1], p) <= 0:
                h.pop()
            h.append(p)
        return h
    lower, upper = half(pts), half(pts[::-1])
    return np.array(lower[:-1] + upper[:-1])


def max_diameter(pts_rc: np.ndarray, spacing_rc: tuple[float, float]) -> tuple[float, np.ndarray, np.ndarray]:
    """Largest centre-to-centre distance (mm) within a pixel set, with its two endpoints (row, col)."""
    xy = pts_rc.astype(float) * np.array(spacing_rc)
    h = _hull(xy)
    if len(h) == 1:
        return 0.0, pts_rc[0], pts_rc[0]
    d = np.sqrt(((h[:, None, :] - h[None, :, :]) ** 2).sum(-1))
    i, j = np.unravel_index(np.argmax(d), d.shape)
    return float(d[i, j]), h[i] / np.array(spacing_rc), h[j] / np.array(spacing_rc)


def largest_axial(mask3d: np.ndarray, spacing_rc: tuple[float, float]) -> dict | None:
    """mask3d indexed (slice, row, col). Returns the largest axial diameter over all 2D regions."""
    best = None
    for k in np.nonzero(mask3d.reshape(mask3d.shape[0], -1).any(1))[0]:
        for comp in components_2d(mask3d[k]):
            d, a, b = max_diameter(comp, spacing_rc)
            if best is None or d > best["mm"]:
                best = {"mm": d, "slice": int(k), "a": a, "b": b,
                        "area_mm2": float(len(comp) * spacing_rc[0] * spacing_rc[1])}
    return best


# ---------------- WAW-TACE (.seg.nrrd) ----------------
def read_nrrd(data: bytes) -> tuple[np.ndarray, dict]:
    """Minimal reader for attached-header NRRD (raw or gzip); returns array indexed (z, y, x)."""
    end = data.find(b"\n\n")
    header = {}
    for line in data[:end].decode("latin1").splitlines()[1:]:
        if line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        header[k.strip()] = v.lstrip("=").strip()
    raw = data[end + 2:]
    if header.get("encoding") in ("gzip", "gz"):
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    dtype = {"short": "<i2", "int16": "<i2", "unsigned char": "u1", "uchar": "u1", "uint8": "u1",
             "unsigned short": "<u2", "ushort": "<u2", "int": "<i4"}[header["type"]]
    sizes = [int(s) for s in header["sizes"].split()]
    arr = np.frombuffer(raw, dtype=dtype)[: int(np.prod(sizes))].reshape(sizes[::-1])
    vecs = [tuple(float(x) for x in v.strip("()").split(",")) for v in re.findall(r"\([^)]*\)", header["space directions"])]
    header["spacing_xyz"] = [float(np.linalg.norm(v)) for v in vecs]
    return arr, header


def waw_rows() -> list[dict]:
    import pandas as pd
    clin = pd.read_excel(WAW_CLINICAL)
    ref = {}
    for _, r in clin.iterrows():
        dias = [float(r[f"lesion{i}_diameter"]) for i in (1, 2, 3) if pd.notna(r.get(f"lesion{i}_diameter"))]
        ref[str(int(r["PATPRI"]))] = max(dias) if dias else None
    rows = []
    with zipfile.ZipFile(WAW_MASKS) as z:
        for name in sorted(n for n in z.namelist() if n.endswith(".nrrd")):
            patient, phase, tumour = Path(name).name.split("_")[:3]
            arr, h = read_nrrd(z.read(name))
            sx, sy, _ = h["spacing_xyz"]
            best = largest_axial(arr > 0, (sy, sx))
            if best is None:
                continue
            rows.append({"dataset": "WAW-TACE", "patient_id": patient, "mask": Path(name).name,
                         "phase": f"code {phase}", "segment": f"tumour {tumour}",
                         "measured_size_mm": round(best["mm"], 1), "slice_z_mm": "",
                         "region_area_mm2": round(best["area_mm2"], 1),
                         "reference_size_mm": ref.get(patient), "reference_source":
                         "clinical largest lesion diameter, axial, portal phase (dataset)",
                         "notes": "phase code as given in ct_hcc_metadata_v2.csv"})
    return rows


# ---------------- HCC-TACE-Seg (DICOM SEG) ----------------
def load_study(study_dir: Path) -> dict:
    """CT images grouped by (series, acquisition number) and the expert SEG, for one study."""
    import pydicom
    cts, seg = defaultdict(dict), None
    for sdir in study_dir.iterdir():
        files = sorted(sdir.glob("*.dcm"))
        if not files:
            continue
        if sdir.name.startswith("SEG_"):
            seg = pydicom.dcmread(files[0])
            continue
        for f in files:
            d = pydicom.dcmread(f)
            cts[d.SOPInstanceUID] = {"ds": d, "series": d.SeriesInstanceUID, "acq": int(getattr(d, "AcquisitionNumber", 1) or 1),
                                     "z": round(float(d.ImagePositionPatient[2]), 2)}
    return {"cts": cts, "seg": seg}


def seg_masks(study: dict) -> dict:
    """{segment label: {(series, acq, z): 2D bool mask}} from the SEG's per-frame references."""
    seg = study["seg"]
    labels = {s.SegmentNumber: s.SegmentLabel for s in seg.SegmentSequence}
    frames = seg.pixel_array
    if frames.ndim == 2:
        frames = frames[None]
    # fallback when frames carry no source-image reference: the acquisition the SEG references overall
    ref_uids = [i.ReferencedSOPInstanceUID for s in getattr(seg, "ReferencedSeriesSequence", [])
                for i in getattr(s, "ReferencedInstanceSequence", [])]
    ref_cts = [study["cts"][u] for u in ref_uids if u in study["cts"]]
    ref_acqs = {(c["series"], c["acq"]) for c in ref_cts}
    default = next(iter(ref_acqs)) if len(ref_acqs) == 1 else None
    out = defaultdict(dict)
    for i, fg in enumerate(seg.PerFrameFunctionalGroupsSequence):
        num = fg.SegmentIdentificationSequence[0].ReferencedSegmentNumber
        deriv = getattr(fg, "DerivationImageSequence", None)
        src = deriv[0].SourceImageSequence if deriv and len(deriv) and "SourceImageSequence" in deriv[0] else None
        ct = study["cts"].get(src[0].ReferencedSOPInstanceUID) if src and len(src) else None
        if ct is not None:
            key = (ct["series"], ct["acq"], ct["z"])
        elif default is not None:
            z = round(float(fg.PlanePositionSequence[0].ImagePositionPatient[2]), 2)
            key = (default[0], default[1], z)
        else:
            continue                                   # ambiguous: skip rather than guess the phase
        out[labels[num]][key] = out[labels[num]].get(key, np.zeros(frames[i].shape, bool)) | frames[i].astype(bool)
    return out


def _hu(d) -> np.ndarray:
    return d.pixel_array.astype(np.float32) * float(getattr(d, "RescaleSlope", 1)) + float(getattr(d, "RescaleIntercept", 0))


def label_phases(study: dict, masks: dict) -> dict:
    """{(series, acq): (label, mean aorta HU)}, using the aorta mask applied to each acquisition."""
    aorta = masks.get("Abdominal aorta", {})
    if not aorta:
        return {}
    series = next(iter(aorta))[0]
    by_pos = {(c["series"], c["acq"], c["z"]): c for c in study["cts"].values() if c["series"] == series}
    acqs = sorted({k[1] for k in by_pos})
    means = {}
    for acq in acqs:
        vals = []
        for (_, _, z), m in aorta.items():
            c = by_pos.get((series, acq, z))
            if c is not None and m.shape == c["ds"].pixel_array.shape:
                vals.append(_hu(c["ds"])[m])
        if vals:
            means[acq] = float(np.concatenate(vals).mean())
    if len(means) < 2:
        return {(series, a): ("single phase", v) for a, v in means.items()}
    ranked = sorted(means, key=means.get, reverse=True)       # aortic attenuation: arterial > portal venous > later
    if means[ranked[0]] - means[ranked[1]] < MIN_PHASE_GAP_HU:
        return {(series, a): ("phase unresolved", v) for a, v in means.items()}
    labels = {(series, ranked[0]): ("arterial", means[ranked[0]]), (series, ranked[1]): ("portal venous", means[ranked[1]])}
    labels.update({(series, a): ("later phase", means[a]) for a in ranked[2:]})
    return labels


def hcc_patient(pdir: Path) -> dict | None:
    study_dir = next((s for s in pdir.iterdir() if any(x.name.startswith("SEG_") for x in s.iterdir())), None)
    if study_dir is None:
        return None
    study = load_study(study_dir)
    masks = seg_masks(study)
    mass = masks.get("Mass", {})
    if not mass:
        return None
    counts = defaultdict(int)
    for k in mass:
        counts[(k[0], k[1])] += 1
    series, acq = max(counts, key=counts.get)            # the acquisition the mask was drawn on
    zs = sorted(k[2] for k in mass if (k[0], k[1]) == (series, acq))
    vol = np.stack([mass[(series, acq, z)] for z in zs])
    ref_ds = next(c["ds"] for c in study["cts"].values() if c["series"] == series)
    sy, sx = (float(x) for x in ref_ds.PixelSpacing)
    best = largest_axial(vol, (sy, sx))
    phases = label_phases(study, masks)
    return {"patient": pdir.name, "study": study, "masks": masks, "series": series, "acq": acq, "zs": zs,
            "best": best, "spacing": (sy, sx), "phases": phases}


def hcc_rows(pdirs: list[Path]) -> list[dict]:
    rows = []
    for pdir in pdirs:
        p = hcc_patient(pdir)
        if p is None or p["best"] is None:
            continue
        label, hu = p["phases"].get((p["series"], p["acq"]), ("phase unresolved", float("nan")))
        rows.append({"dataset": "HCC-TACE-Seg", "patient_id": p["patient"], "mask": "SEG segment 'Mass'",
                     "phase": f"{label} (acquisition {p['acq']}, aorta {hu:.0f} HU)", "segment": "Mass",
                     "measured_size_mm": round(p["best"]["mm"], 1), "slice_z_mm": p["zs"][p["best"]["slice"]],
                     "region_area_mm2": round(p["best"]["area_mm2"], 1), "reference_size_mm": "",
                     "reference_source": "", "notes": "pre-treatment CT; largest connected tumour region"})
    return rows


# ---------------- preview ----------------
def preview(patient: str) -> Path | None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    p = hcc_patient(HCC_DICOM / patient)
    if p is None or p["best"] is None:
        return None
    z = p["zs"][p["best"]["slice"]]
    mask = p["masks"]["Mass"][(p["series"], p["acq"], z)]
    imgs = {c["acq"]: c["ds"] for c in p["study"]["cts"].values() if c["series"] == p["series"] and c["z"] == z}
    rank = {"arterial": 0, "portal venous": 1}
    order = sorted(imgs, key=lambda a: rank.get(p["phases"].get((p["series"], a), ("",))[0], 2))
    labelled = [a for a in order if p["phases"].get((p["series"], a), ("",))[0] in rank]
    if len(labelled) == 2:                                    # show exactly arterial and portal venous
        order = labelled
    fig, axes = plt.subplots(1, len(order), figsize=(5.2 * len(order), 5.6), dpi=130)
    axes = np.atleast_1d(axes)
    a, b = p["best"]["a"], p["best"]["b"]
    for ax, acq in zip(axes, order):
        label, hu = p["phases"].get((p["series"], acq), ("phase unresolved", float("nan")))
        ax.imshow(np.clip(_hu(imgs[acq]), -135, 215), cmap="gray")             # abdomen window W350 L40
        ax.contour(mask, levels=[0.5], colors=["#ff9f0a"], linewidths=1.2)
        ax.plot([a[1], b[1]], [a[0], b[0]], color="#30d158", linewidth=1.4)
        ax.set_title(f"{label.capitalize()} (aorta {hu:.0f} HU)", fontsize=11)
        ax.axis("off")
    fig.suptitle(f"{patient}  ·  HCC-TACE-Seg (TCIA/IDC, CC BY 4.0)  ·  max axial diameter "
                 f"{p['best']['mm']:.1f} mm  ·  z = {z} mm", fontsize=11)
    fig.text(0.5, 0.02, "Orange: expert tumour mask (drawn on acquisition "
             f"{p['acq']}). Green: maximum in-plane diameter. Phase labels from aortic attenuation. "
             "Not a LI-RADS assessment.", ha="center", fontsize=8, color="#555")
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / f"ct_preview_{patient}.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sizes")
    pv = sub.add_parser("preview")
    pv.add_argument("--patients", nargs="+", required=True)
    a = ap.parse_args()
    if a.cmd == "sizes":
        rows = (waw_rows() if WAW_MASKS.exists() else [])
        rows += hcc_rows(sorted(d for d in HCC_DICOM.iterdir() if d.is_dir()) if HCC_DICOM.exists() else [])
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"{len(rows)} rows -> {OUT_CSV}")
    else:
        for patient in a.patients:
            print(patient, "->", preview(patient))


if __name__ == "__main__":
    main()
