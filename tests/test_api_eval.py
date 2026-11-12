"""HTTP API (LLM mocked) and evaluation code."""
import json

from fastapi.testclient import TestClient

from radsenvelope.api import app as appmod
from radsenvelope.evaluation import generator, metrics, real_cases
from radsenvelope.extraction.schema import Extraction

client = TestClient(appmod.app)


def _fake(states, size=25):
    d = {"size_mm": size, "size_evidence": f"{size} mm"}
    for k in ("aphe", "washout", "capsule", "growth", "af_malignant", "af_benign"):
        st = states.get(k, "not_documented")
        d[k] = {"state": st, "evidence": ""}
    return Extraction.model_validate(d)


def test_health_rules_samples():
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/rules").json()["label"].startswith("LI-RADS")
    assert len(client.get("/api/samples").json()) >= 8


def test_analyse_lexicon():
    rep = client.get("/api/samples").json()[0]["report"]
    out = client.post("/api/analyse", json={"report": rep, "extractor": "lexicon"}).json()
    o = out["observations"][0]
    assert o["result"]["acr_category"] == "LR-3" and o["result"]["decision_critical"]
    assert out["consistency"]["consistent"]


def test_self_consistency_path(monkeypatch):
    draws = [_fake({"aphe": "present", "washout": "present"}), _fake({"aphe": "present", "washout": "absent"}),
             _fake({"aphe": "present", "washout": "present"})]
    monkeypatch.setattr(appmod.llm, "available", lambda *a: (True, "test-model"))
    import radsenvelope.pipeline as pipe
    monkeypatch.setattr(pipe.llm, "available", lambda *a: (True, "test-model"))
    monkeypatch.setattr(pipe.llm, "sample", lambda text, k: (draws, 1.0))
    out = client.post("/api/analyse", json={"report": "Segment VI: 25 mm observation with APHE and washout.",
                                            "extractor": "llm", "samples": 3}).json()
    o = out["observations"][0]
    assert o["features"]["washout"] == "uncertain"
    assert o["confidence"]["washout"]["source"] == "extractor"
    assert o["result"]["envelope"] == ["LR-4", "LR-5"] and o["result"]["decision_critical"]


def test_llm_only_unavailable_returns_503(monkeypatch):
    import radsenvelope.pipeline as pipe
    monkeypatch.setattr(pipe.llm, "available", lambda *a: (False, "offline"))
    r = client.post("/api/analyse", json={"report": "Segment VI: 18 mm observation.", "extractor": "llm"})
    assert r.status_code == 503


def test_recompute_answers_question():
    body = {"observations": [{"label": "Segment VI", "size_mm": 18, "size_tolerance_mm": 2,
                              "features": {"aphe": "present", "washout": "present", "capsule": "absent",
                                           "growth": "not_documented"}}]}
    out = client.post("/api/recompute", json=body).json()
    assert out["observations"][0]["result"]["acr_category"] == "LR-5" and out["consistency"]["consistent"]


def test_audit():
    reps = [s["report"] for s in client.get("/api/samples").json()]
    s = client.post("/api/audit", json={"reports": reps, "extractor": "lexicon"}).json()["summary"]
    assert s["reports"] == 9 and s["contradictions"] == 3 and s["needs_review"] == 2


def test_generator_is_deterministic_and_labelled():
    a, b = generator.generate(20, seed=3), generator.generate(20, seed=3)
    assert a == b
    assert all(c["gold_category"] in c["gold_envelope"] for c in a)


def test_metrics():
    rows = [{"gold_category": "LR-3", "pred_category": "LR-3", "gold_envelope": ["LR-3"], "pred_envelope": ["LR-3"],
             "gold_critical": False, "pred_critical": False},
            {"gold_category": "LR-5", "pred_category": "LR-4", "gold_envelope": ["LR-5"], "pred_envelope": ["LR-4", "LR-5"],
             "gold_critical": False, "pred_critical": True}]
    s = metrics.category_scores(rows)
    assert s["category_accuracy"] == 0.5 and s["within_one"] == 1.0 and s["gold_in_envelope"] == 1.0
    f = metrics.feature_scores([({"aphe": "present"}, {"aphe": "present"}), ({"aphe": "absent"}, {"aphe": "present"})], ("aphe",))
    assert f["aphe"]["accuracy"] == 0.5


def test_real_cases_evaluation(tmp_path):
    csv_path = tmp_path / "cases.csv"
    csv_path.write_text(
        "id,url,author,license,modality,findings_text,radiologist_category,collected_by,collected_on,notes\n"
        "R1,https://example.org/1,Dr A,CC BY-NC-SA 3.0,MRI,\"25 mm observation with arterial phase hyperenhancement, "
        "nonperipheral washout and an enhancing capsule.\",LR-5,x,2026-11-12,\n"
        "R2,https://example.org/2,Dr B,CC BY-NC-SA 3.0,CT,\"32 mm mass with rim arterial phase hyperenhancement.\",LR-M,x,2026-11-12,\n"
        "TODO-3,TODO,TODO,,,TODO,TODO,,,\n", encoding="utf-8")
    rows = real_cases.load(csv_path)
    assert len(rows) == 2
    res = real_cases.evaluate(rows, "lexicon")
    assert res["summary"]["exact_agreement"] == 1.0 and res["summary"]["correct_deferrals"] == "1/1"
    assert real_cases.normalise("LI-RADS 4") == "LR-4" and real_cases.normalise("lr-m") == "LR-M"


def test_extract_text_txt_and_docx():
    import base64
    import io
    import zipfile
    txt = base64.b64encode(b"Segment VI: 18 mm observation with washout.").decode()
    assert "18 mm" in client.post("/api/extract-text", json={"filename": "r.txt", "content_b64": txt}).json()["text"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Segment II: 25 mm observation</w:t></w:r></w:p>"
                                        "<w:p><w:r><w:t>with washout &amp; capsule.</w:t></w:r></w:p></w:body></w:document>")
    docx = base64.b64encode(buf.getvalue()).decode()
    text = client.post("/api/extract-text", json={"filename": "r.docx", "content_b64": docx}).json()["text"]
    assert text == "Segment II: 25 mm observation\nwith washout & capsule."
    assert client.post("/api/extract-text", json={"filename": "r.pdf", "content_b64": txt}).status_code == 415
