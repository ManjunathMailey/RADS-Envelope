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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from radsenvelope import __version__
from radsenvelope.engine.ruleset import FEATURE_LABELS, FEATURES, get_ruleset
from radsenvelope.extraction import llm
from radsenvelope.pipeline import Settings, analyse_report, finalize, run_observation

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


class AnalyseRequest(BaseModel):
    report: str = Field(min_length=10)
    extractor: Literal["auto", "llm", "lexicon"] = "auto"
    samples: int = Field(1, ge=1, le=7)
    size_tolerance_mm: float = Field(2.0, ge=0, le=10)
    high_risk: bool = True


class ObservationIn(BaseModel):
    label: str
    features: dict
    size_mm: Optional[float]
    size_tolerance_mm: float = 2.0
    defer_reasons: list[str] = []


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
        return analyse_report(req.report, Settings(req.extractor, req.samples, req.size_tolerance_mm, req.high_risk))
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@app.post("/api/recompute")
def recompute(req: RecomputeRequest):
    """Engine only: the radiologist corrected a feature or answered a decisive question."""
    obs = []
    for o in req.observations:
        result = run_observation(o.label, o.features, o.size_mm, o.size_tolerance_mm, req.high_risk, o.defer_reasons)
        obs.append({"label": o.label, "size_mm": o.size_mm, "features": o.features, "result": result})
    return {"observations": [{"label": o["label"], "result": o["result"]} for o in obs], **finalize(obs)}


@app.post("/api/audit")
def audit(req: AuditRequest):
    rows = []
    for i, rep in enumerate(r for r in req.reports if r.strip()):
        out = analyse_report(rep, Settings(extractor=req.extractor))
        for o in out["observations"]:
            res = o["result"]
            rows.append({"report": i + 1, "label": o["label"], "excerpt": o["text"][:160],
                         "status": res["status"], "computed": res.get("acr_category"),
                         "envelope": res.get("envelope"), "critical": bool(res.get("decision_critical")),
                         "stated": o["audit"]["stated"] if o["audit"] else None,
                         "contradiction": bool(o["audit"] and o["audit"]["contradiction"]),
                         "reasons": res.get("reasons")})
    return {"summary": {"reports": len({r["report"] for r in rows}), "observations": len(rows),
                        "contradictions": sum(r["contradiction"] for r in rows),
                        "decision_critical": sum(r["critical"] for r in rows),
                        "needs_review": sum(r["status"] != "assigned" for r in rows)},
            "rows": rows, "extractor": req.extractor}


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


app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")
