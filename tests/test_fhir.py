"""FHIR R4 export: structure, resolvable references, engine-consistent categories, no invented codes."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from radsenvelope.api import app as appmod
from radsenvelope.export.fhir import LOCAL, UCUM, to_fhir_bundle
from radsenvelope.pipeline import Settings, analyse_report

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = json.loads((ROOT / "data" / "samples" / "reports.json").read_text(encoding="utf-8"))
S10 = json.loads((ROOT / "data" / "samples" / "longitudinal.json").read_text(encoding="utf-8"))[0]
LEX = Settings(extractor="lexicon")
client = TestClient(appmod.app)


def _references(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "reference":
                yield v
            else:
                yield from _references(v)
    elif isinstance(node, list):
        for v in node:
            yield from _references(v)


def _component(obs, code):
    return next(c for c in obs["component"] if c["code"]["coding"][0]["code"] == code)


def test_bundle_structure_and_resource_types():
    b = to_fhir_bundle(analyse_report(SAMPLES[8]["report"], LEX))           # S9: two observations
    assert (b["resourceType"], b["type"]) == ("Bundle", "collection")
    types = [e["resource"]["resourceType"] for e in b["entry"]]
    assert types == ["DiagnosticReport", "Observation", "Observation"]
    dr = b["entry"][0]["resource"]
    assert dr["status"] == "preliminary" and dr["conclusion"].startswith("IMPRESSION:")
    assert "presentedForm" not in dr and len(dr["result"]) == 2
    for e in b["entry"][1:]:
        o = e["resource"]
        assert o["status"] == "preliminary" and o["code"]["text"] == "LI-RADS category"
        assert o["bodySite"]["text"] in ("Segment VI", "Segment II") and o["note"][0]["text"].startswith("Decision support")


def test_every_reference_resolves_and_ids_are_deterministic():
    analysis = analyse_report(S10["report"], LEX, prior=S10["prior"])
    b1, b2 = to_fhir_bundle(analysis), to_fhir_bundle(analysis)
    assert b1 == b2
    urls = [e["fullUrl"] for e in b1["entry"]]
    assert all(u.startswith("urn:uuid:") for u in urls) and len(set(urls)) == len(urls)
    refs = list(_references(b1))
    assert refs and all(r in urls for r in refs)
    for e in b1["entry"]:
        assert e["fullUrl"] == "urn:uuid:" + e["resource"]["id"]


def test_observation_category_equals_engine_for_every_sample():
    for s in SAMPLES + [S10]:
        analysis = analyse_report(s["report"], LEX, prior=s.get("prior"))
        obs = [e["resource"] for e in to_fhir_bundle(analysis)["entry"][1:]]
        assert len(obs) == len(analysis["observations"]), s["id"]
        for fo, ao in zip(obs, analysis["observations"]):
            r = ao["result"]
            expected = r["acr_category"] if r["status"] == "assigned" else r["status"]
            assert fo["valueCodeableConcept"]["text"] == expected, s["id"]
            assert _component(fo, "decision-critical")["valueBoolean"] == bool(r.get("decision_critical"))
            if r["status"] == "assigned":
                assert _component(fo, "certainty-envelope")["valueString"] == ", ".join(r["envelope"])


def test_size_uses_ucum_and_features_are_present():
    o = to_fhir_bundle(analyse_report(SAMPLES[0]["report"], LEX))["entry"][1]["resource"]
    size = _component(o, "size")["valueQuantity"]
    assert size == {"value": 18.0, "unit": "mm", "system": UCUM, "code": "mm"}
    assert _component(o, "washout")["valueCodeableConcept"]["text"] == "uncertain"
    missing = to_fhir_bundle(analyse_report(SAMPLES[7]["report"], LEX))["entry"][1]["resource"]   # S8: no size
    assert "dataAbsentReason" in _component(missing, "size")


def test_longitudinal_result_is_exported():
    o = to_fhir_bundle(analyse_report(S10["report"], LEX, prior=S10["prior"]))["entry"][1]["resource"]
    assert o["valueCodeableConcept"]["text"] == "LR-5"
    assert _component(o, "growth-computed")["valueCodeableConcept"]["text"] == "present"
    assert _component(o, "growth-percent")["valueQuantity"]["code"] == "%"
    assert _component(o, "growth-interval")["valueQuantity"] == {"value": 123, "unit": "d", "system": UCUM, "code": "d"}
    assert _component(o, "prior-size")["valueQuantity"]["value"] == 10.0


def test_no_invented_standard_codes():
    for s in SAMPLES + [S10]:
        text = json.dumps(to_fhir_bundle(analyse_report(s["report"], LEX, prior=s.get("prior"))))
        assert "loinc.org" not in text and "snomed.info" not in text and "radlex" not in text.lower()
    b = to_fhir_bundle(analyse_report(S10["report"], LEX))
    systems = {c["system"] for e in b["entry"] for c in json.loads(json.dumps(e["resource"]))["code"]["coding"]}
    assert systems == {LOCAL}


def test_api_export_rederives_categories_and_validates_input():
    analysis = client.post("/api/analyse", json={"report": S10["report"], "extractor": "lexicon",
                                                 "prior": S10["prior"]}).json()
    b = client.post("/api/export/fhir", json=analysis).json()
    assert b["resourceType"] == "Bundle" and b["entry"][1]["resource"]["valueCodeableConcept"]["text"] == "LR-5"
    # a stale or hand-edited category is replaced by the engine's category
    tampered = json.loads(json.dumps(analysis))
    tampered["observations"][0]["result"]["acr_category"] = "LR-2"
    tampered["observations"][0]["features"]["growth"] = "absent"            # radiologist edit, not re-computed
    b = client.post("/api/export/fhir", json=tampered).json()
    assert b["entry"][1]["resource"]["valueCodeableConcept"]["text"] == "LR-4"
    assert "LI-RADS 4" in b["entry"][0]["resource"]["conclusion"]
    assert client.post("/api/export/fhir", json={"observations": []}).status_code == 422
    assert client.post("/api/export/fhir", json={"observations": [{"label": "x"}]}).status_code == 422
