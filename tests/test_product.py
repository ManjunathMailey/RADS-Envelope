"""Product features: report check, impression diff, addendum templates, completeness, batch CSV export."""
import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radsenvelope.api import app as appmod
from radsenvelope.api.product import (ADDENDUM, CSV_COLUMNS, addendum, audit_csv, completeness, impression_diff,
                                      report_check)
from radsenvelope.engine.ruleset import FEATURES

client = TestClient(appmod.app)
S10 = json.loads((Path(__file__).resolve().parents[1] / "data" / "samples" / "longitudinal.json").read_text())[0]


# ---------------- addendum templates ----------------
def test_addendum_template_for_every_feature_and_state():
    for k in FEATURES:
        for state in ("present", "absent"):
            s = addendum(k, state)
            assert s == ADDENDUM[k][state] and s.endswith(".") and s[0].isupper()
    assert addendum("washout", "present") == "Nonperipheral washout is present on the portal venous phase."
    assert addendum("capsule", "absent", label="Segment VI") == "Segment VI: There is no enhancing capsule."
    assert addendum("size", size_mm=19.5) == "On re-measurement, the observation measures 19.5 mm."
    assert addendum("washout", "present") == addendum("washout", "present")          # deterministic


def test_addendum_rejects_unknown_input():
    with pytest.raises(ValueError):
        addendum("washout", "uncertain")
    with pytest.raises(ValueError):
        addendum("size")
    assert client.post("/api/addendum", json={"feature": "aphe", "state": "present"}).json()["sentence"].startswith("Nonrim")
    assert client.post("/api/addendum", json={"feature": "size"}).status_code == 422
    assert client.post("/api/addendum", json={"feature": "colour", "state": "present"}).status_code == 422


# ---------------- completeness ----------------
def test_completeness_counts_required_items():
    feats = {"aphe": "present", "washout": "uncertain", "capsule": "not_documented", "growth": "not_documented"}
    c = completeness(feats, 18.0)
    assert (c["documented"], c["total"], c["missing"]) == (3, 4, ["capsule"])      # hedged counts as documented
    assert c["missing_labels"] == ["Enhancing capsule"] and c["score"] == 0.75
    c = completeness(feats, None, has_prior=True)                                  # growth required with a prior
    assert (c["documented"], c["total"], c["missing"]) == (2, 5, ["capsule", "size", "growth"])
    full = completeness({"aphe": "absent", "washout": "absent", "capsule": "present"}, 25)
    assert full["score"] == 1.0 and full["missing"] == []


# ---------------- report check ----------------
def _res(cat, env, status="assigned"):
    return {"status": status, "acr_category": cat, "envelope": env}


def test_report_check_status_logic():
    assert report_check(None, _res("LR-5", ["LR-5"])) is None
    assert report_check("LR-5", _res("LR-5", ["LR-5"]))["status"] == "consistent"
    assert report_check("LR-3", _res("LR-5", ["LR-5"]))["status"] == "contradicts"
    inside = report_check("LR-5", _res("LR-3", ["LR-3", "LR-4", "LR-5"]))
    assert inside["status"] == "inside_envelope" and "not the ACR tie-break" in inside["label"]
    assert report_check("LR-M", _res(None, None, "defer"))["status"] == "consistent"
    assert report_check("LR-4", _res(None, None, "defer"))["status"] == "not_assessable"
    assert report_check("LR-4", _res(None, None, "not_assignable"))["status"] == "not_assessable"


def test_impression_diff_is_word_level():
    d = impression_diff("Segment VII: LI-RADS 3.", "Segment VII: LI-RADS 5 (definitely HCC).")
    assert {"op": "equal", "text": "Segment VII: LI-RADS"} in d
    assert {"op": "delete", "text": "3."} in d and {"op": "insert", "text": "5 (definitely HCC)."} in d
    assert impression_diff("same words", "same words") == [{"op": "equal", "text": "same words"}]


def test_review_endpoint_on_contradicting_sample():
    s2 = client.get("/api/samples").json()[1]                     # impression says LR-3, findings support LR-5
    a = client.post("/api/analyse", json={"report": s2["report"], "extractor": "lexicon"}).json()
    rv = client.post("/api/review", json=a).json()
    o = rv["observations"][0]
    assert o["check"]["status"] == "contradicts" and o["check"]["stated"] == "LR-3" and o["check"]["computed"] == "LR-5"
    assert o["completeness"]["total"] == 4 and rv["has_stated_impression"] and rv["diff"]
    nostated = client.post("/api/analyse", json={"report": S10["report"], "extractor": "lexicon", "prior": S10["prior"]}).json()
    rv = client.post("/api/review", json=nostated).json()
    assert rv["observations"][0]["check"] is None and rv["diff"] == []
    assert rv["observations"][0]["completeness"]["total"] == 5               # growth required: a prior was given
    assert client.post("/api/review", json={"observations": []}).status_code == 422


# ---------------- batch and CSV export ----------------
def test_audit_summary_and_csv_columns():
    reps = [s["report"] for s in client.get("/api/samples").json()]
    out = client.post("/api/audit", json={"reports": reps, "extractor": "lexicon"}).json()
    s = out["summary"]
    assert s["reports"] == 9 and s["contradictions"] == 3 and s["reports_contradicting_rules"] == 3
    assert 0 < s["mean_completeness"] <= 1 and s["most_missing"]
    assert all("check" in r and "completeness" in r and "management" in r for r in out["rows"])
    text = client.post("/api/audit/csv", json={"rows": out["rows"]})
    assert text.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(text.text)))
    assert list(rows[0].keys()) == CSV_COLUMNS == ["id", "stated", "computed", "envelope", "management",
                                                   "decision_critical", "completeness", "missing"]
    assert len(rows) == len(out["rows"]) and rows[1]["stated"] == "LR-3" and rows[1]["computed"] == "LR-5"
    assert rows[0]["completeness"].count("/") == 1


def test_audit_csv_function_handles_missing_fields():
    text = audit_csv([{"report": 1, "label": "Segment VI", "status": "defer", "envelope": None}])
    row = next(csv.DictReader(io.StringIO(text)))
    assert row["id"] == "1-Segment VI" and row["computed"] == "defer" and row["decision_critical"] == "False"
