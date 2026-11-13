"""
HTTP API and web UI.

    uvicorn radsenvelope.api.app:app --port 8000
"""
from __future__ import annotations

import base64
import io
import json
import re
import threading
import zipfile
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from radsenvelope import __version__
from radsenvelope.api.product import addendum, audit_csv, completeness, impression_diff, management_text, report_check
from radsenvelope.engine.longitudinal import normalise_modality
from radsenvelope.engine.ruleset import FEATURE_LABELS, FEATURES, get_ruleset
from radsenvelope.export.fhir import to_fhir_bundle
from radsenvelope.extraction import llm
from radsenvelope.extraction.segment import stated_categories
from radsenvelope.pipeline import Settings, analyse_report, finalize, recompare, run_observation

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
STATE = {"warm": False, "warming": False}


def _warm_up() -> None:
    STATE["warming"] = True
    try:
        if llm.available()[0]:
            llm.extract("Segment II: 12 mm observation. No washout.")
            STATE["warm"] = True
    except Exception:
        pass
    finally:
        STATE["warming"] = False


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="RADS-Envelope", version=__version__, lifespan=lifespan)


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PriorIn(BaseModel):
    """A prior study for longitudinal comparison. Only its sizes are used."""
    report: str = Field(min_length=5)
    prior_date: str
    current_date: Optional[str] = None
    modality: str

    @field_validator("prior_date", "current_date")
    @classmethod
    def _iso_date(cls, v, info):
        if v is None:
            return v
        try:
            if not _ISO_DATE.match(v):
                raise ValueError
            date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"{info.field_name} must be a valid ISO date (yyyy-mm-dd), got {v!r}") from None
        return v

    @field_validator("modality")
    @classmethod
    def _modality(cls, v):
        m = normalise_modality(v)
        if m not in ("CT", "MRI", "Ultrasound"):
            raise ValueError(f"modality must be CT, MRI or Ultrasound, got {v!r}")
        return m


class AnalyseRequest(BaseModel):
    report: str = Field(min_length=10)
    extractor: Literal["auto", "llm", "lexicon", "consensus"] = "auto"
    samples: int = Field(1, ge=1, le=7)
    size_tolerance_mm: float = Field(2.0, ge=0, le=10)
    high_risk: bool = True
    prior: Optional[PriorIn] = None


class ObservationIn(BaseModel):
    label: str
    features: dict
    size_mm: Optional[float]
    size_tolerance_mm: float = 2.0
    defer_reasons: list[str] = []
    longitudinal: Optional[dict] = None


class RecomputeRequest(BaseModel):
    observations: list[ObservationIn]
    high_risk: bool = True


class FileIn(BaseModel):
    filename: str
    content_b64: str = Field(max_length=14_000_000)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", " ", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(a, b)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


class AuditRequest(BaseModel):
    reports: list[str]
    extractor: Literal["auto", "llm", "lexicon"] = "auto"


@app.get("/api/health")
def health():
    ok, msg = llm.available()
    return {"version": __version__, "llm_ready": ok and STATE["warm"], "llm_installed": ok,
            "warming": STATE["warming"], "llm": msg, "model": llm.MODEL, "rules": get_ruleset().label}


@app.get("/api/samples")
def samples():
    return json.loads((ROOT / "data" / "samples" / "reports.json").read_text(encoding="utf-8"))


@app.get("/api/samples/longitudinal")
def samples_longitudinal():
    return json.loads((ROOT / "data" / "samples" / "longitudinal.json").read_text(encoding="utf-8"))


@app.get("/api/rules")
def rules():
    rs = get_ruleset()
    return {"label": rs.label, "cutoffs": rs.cutoffs, "buckets": rs.raw["size_buckets"],
            "table": rs.raw["core_table"], "ancillary": rs.raw["ancillary"],
            "management": rs.raw["management"], "meaning": rs.raw["category_meaning"],
            "features": [{"key": k, "label": FEATURE_LABELS[k]} for k in FEATURES]}


@app.post("/api/analyse")
def analyse(req: AnalyseRequest):
    try:
        return analyse_report(req.report, Settings(req.extractor, req.samples, req.size_tolerance_mm, req.high_risk),
                              prior=req.prior.model_dump() if req.prior else None)
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@app.post("/api/recompute")
def recompute(req: RecomputeRequest):
    """Engine only: the radiologist corrected a feature or answered a decisive question.
    When an observation carries a longitudinal block, the comparison with the prior is redone
    for the posted size and tolerance and the merge policy re-applied; the updated features are
    returned with it."""
    obs = []
    for o in req.observations:
        features, block = o.features, o.longitudinal
        if block is not None:
            features, block = recompare(o.features, o.size_mm, o.size_tolerance_mm, block)
        result = run_observation(o.label, features, o.size_mm, o.size_tolerance_mm, req.high_risk, o.defer_reasons)
        item = {"label": o.label, "size_mm": o.size_mm, "features": features, "result": result}
        if block is not None:
            item["longitudinal"] = block
        obs.append(item)
    out = []
    for o in obs:
        row = {"label": o["label"], "result": o["result"]}
        if "longitudinal" in o:
            row.update(longitudinal=o["longitudinal"], features=o["features"])
        out.append(row)
    return {"observations": out, **finalize(obs)}


def _stated_per_observation(stated_impression: str, n: int) -> list[str | None]:
    """The category written in the report's own impression for each observation (same rule as the pipeline)."""
    stated = stated_categories(stated_impression or "")
    if len(stated) == n:
        return stated
    return [stated[0] if n == 1 and stated else None] * n


def _review_observation(o: dict, stated: str | None) -> dict:
    return {"label": o.get("label"), "check": report_check(stated, o.get("result") or {}),
            "completeness": completeness(o.get("features") or {}, o.get("size_mm"), bool(o.get("longitudinal")))}


@app.post("/api/review")
def review(analysis: dict = Body(...)):
    """Report check, completeness and impression diff for an analysis from /api/analyse (after any edits)."""
    observations = analysis.get("observations")
    if not isinstance(observations, list) or not observations:
        raise HTTPException(422, "Send the analysis returned by /api/analyse: 'observations' must be a non-empty list.")
    stated_text = analysis.get("stated_impression") or ""
    stated = _stated_per_observation(stated_text, len(observations))
    return {"observations": [_review_observation(o, s) for o, s in zip(observations, stated)],
            "has_stated_impression": bool(stated_text.strip()),
            "diff": impression_diff(stated_text, analysis.get("impression") or "") if stated_text.strip() else []}


class AddendumRequest(BaseModel):
    feature: Literal["aphe", "washout", "capsule", "growth", "af_malignant", "af_benign", "size"]
    state: Optional[Literal["present", "absent"]] = None
    size_mm: Optional[float] = None
    label: Optional[str] = None


@app.post("/api/addendum")
def addendum_sentence(req: AddendumRequest):
    try:
        return {"sentence": addendum(req.feature, req.state, req.size_mm, req.label)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/audit")
def audit(req: AuditRequest):
    rows = []
    for i, rep in enumerate(r for r in req.reports if r.strip()):
        out = analyse_report(rep, Settings(extractor=req.extractor))
        stated_all = _stated_per_observation(out["stated_impression"], len(out["observations"]))
        for o, stated in zip(out["observations"], stated_all):
            res = o["result"]
            rv = _review_observation(o, stated)
            rows.append({"report": i + 1, "label": o["label"], "excerpt": o["text"][:160],
                         "status": res["status"], "computed": res.get("acr_category"),
                         "envelope": res.get("envelope"), "critical": bool(res.get("decision_critical")),
                         "stated": o["audit"]["stated"] if o["audit"] else stated,
                         "contradiction": bool(o["audit"] and o["audit"]["contradiction"]),
                         "reasons": res.get("reasons"), "check": rv["check"], "completeness": rv["completeness"],
                         "management": management_text(res)})
    missing = Counter(m for r in rows for m in r["completeness"]["missing_labels"])
    reports = {r["report"] for r in rows}
    contradicting = {r["report"] for r in rows if r["check"] and r["check"]["status"] == "contradicts"}
    return {"summary": {"reports": len(reports), "observations": len(rows),
                        "contradictions": sum(r["contradiction"] for r in rows),
                        "decision_critical": sum(r["critical"] for r in rows),
                        "needs_review": sum(r["status"] != "assigned" for r in rows),
                        "reports_contradicting_rules": len(contradicting),
                        "mean_completeness": round(sum(r["completeness"]["score"] for r in rows) / len(rows), 3) if rows else None,
                        "most_missing": missing.most_common(1)[0][0] if missing else None,
                        "most_missing_count": missing.most_common(1)[0][1] if missing else 0},
            "rows": rows, "extractor": req.extractor}


class AuditCsvRequest(BaseModel):
    rows: list[dict]


@app.post("/api/audit/csv")
def audit_export(req: AuditCsvRequest):
    """CSV of batch results: id, stated, computed, envelope, management, decision_critical, completeness, missing."""
    return Response(audit_csv(req.rows), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="lirads-batch.csv"'})


@app.post("/api/export/fhir")
def export_fhir(analysis: dict = Body(...)):
    """FHIR R4 Bundle for an analysis from /api/analyse (after any edits). Categories and the
    impression are re-derived from the posted features by the engine, so the bundle always
    states the rule-based category, never a stale or hand-edited one."""
    observations = analysis.get("observations")
    if not isinstance(observations, list) or not observations:
        raise HTTPException(422, "Send the analysis returned by /api/analyse: 'observations' must be a non-empty list.")
    high_risk = bool((analysis.get("settings") or {}).get("high_risk", True))
    obs = []
    for i, o in enumerate(observations):
        if not isinstance(o, dict) or not isinstance(o.get("features"), dict) or not o.get("label"):
            raise HTTPException(422, f"Observation {i + 1} needs a 'label' and a 'features' object.")
        prev = o.get("result") or {}
        tol = prev.get("size_tolerance_mm", o.get("size_tolerance_mm", 2.0))
        result = run_observation(o["label"], o["features"], o.get("size_mm"), tol, high_risk,
                                 o.get("defer_reasons") or [])
        item = {"label": o["label"], "size_mm": o.get("size_mm"), "features": o["features"], "result": result}
        if o.get("longitudinal"):
            item["longitudinal"] = o["longitudinal"]
        obs.append(item)
    out = finalize(obs)
    return to_fhir_bundle({"report": analysis.get("report", ""), "rules": get_ruleset().label,
                           "observations": obs, "impression": out["impression"]})


@app.post("/api/extract-text")
def extract_text(f: FileIn):
    """Turn an uploaded report file into plain text (.txt, .md, .docx)."""
    try:
        data = base64.b64decode(f.content_b64)
    except Exception:
        raise HTTPException(400, "The file could not be read.")
    name = f.filename.lower()
    if name.endswith(".docx"):
        try:
            text = _docx_text(data)
        except Exception:
            raise HTTPException(400, "This Word file could not be opened. Save it as .docx or paste the text.")
    elif name.endswith((".txt", ".md", ".text")):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        raise HTTPException(415, "Use a .txt or .docx file, or paste the report text.")
    if len(text.strip()) < 10:
        raise HTTPException(400, "The file does not contain report text.")
    return {"filename": f.filename, "text": text.strip()}


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@app.get("/api/evaluation")
def evaluation():
    bench = ROOT / "data" / "benchmark"
    return {"real": _read(ROOT / "data" / "real" / "results.json"),
            "benchmark": {name: _read(bench / f"results_{name}.json") for name in ("llm", "lexicon")}}


EXAMPLE_CASE = "RP002"          # a development case (never a held-out test case) for the landing page


def _contradiction(res: dict | None) -> dict | None:
    if not res:
        return None
    rate = res["systems"]["B1"]["summary"].get("contradiction_rate")
    return {**rate, "label": res.get("label") or res.get("split"), "generated_at": res.get("generated_at")} if rate else None


@app.get("/api/headline")
def headline():
    """Numbers for the landing page, read from the committed result files at request time."""
    return {"b1_contradiction": {
        "robustness": _contradiction(_read(ROOT / "data" / "benchmark" / "results_comparison.json")),
        "real_dev": _contradiction(_read(ROOT / "data" / "real" / "results.comparison.dev.json"))},
        "sources": ["data/benchmark/results_comparison.json", "data/real/results.comparison.dev.json"]}


@app.get("/api/example")
def example():
    """One attributed real development case for 'See an example'."""
    import csv as _csv
    split = {}
    split_file = ROOT / "data" / "real" / "split.csv"
    if split_file.exists():
        split = {r["id"]: r["split"] for r in _csv.DictReader(open(split_file, encoding="utf-8"))}
    if split.get(EXAMPLE_CASE, "dev") != "dev":
        raise HTTPException(404, "The example case is not a development case.")
    with open(ROOT / "data" / "real" / "radiopaedia_cases.csv", encoding="utf-8-sig", newline="") as fh:
        row = next((r for r in _csv.DictReader(fh) if r["id"] == EXAMPLE_CASE), None)
    if row is None:
        raise HTTPException(404, "Example case not found.")
    return {"id": row["id"], "report": row["findings_text"], "url": row["url"], "author": row["author"],
            "license": row["license"], "radiologist_category": row["radiologist_category"]}


app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


@app.get("/")
def landing():
    return FileResponse(WEB / "landing.html")


@app.get("/app")
def index():
    return FileResponse(WEB / "index.html")
