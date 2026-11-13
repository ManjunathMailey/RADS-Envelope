"""Evidence for panel questions: tolerance sensitivity, deferral precision/recall, per-source results,
repeatability bookkeeping and the annotation status."""
import importlib.util
from pathlib import Path

import pytest

from radsenvelope.evaluation.metrics import system_summary
from radsenvelope.evaluation.repeatability import identical_share
from radsenvelope.evaluation.sensitivity import tolerance_sensitivity

TOOLS = Path(__file__).resolve().parents[1] / "data_tools"


def _ours(id_, gold, size, **feats):
    base = {"aphe": "present", "washout": "absent", "capsule": "absent", "growth": "absent",
            "af_malignant": "not_documented", "af_benign": "not_documented"}
    return {"id": id_, "gold": gold, "size_mm": size, "features": {**base, **feats}, "size_tolerance_mm": 2.0,
            "defer_reasons": []}


def test_tolerance_sensitivity_widens_envelope_near_cutoff():
    rows = [_ours("a", "LR-4", 19.0), _ours("b", "LR-3", 12.0), _ours("c", "LR-5", 30.0, washout="present")]
    t = {r["tolerance_mm"]: r for r in tolerance_sensitivity(rows)}
    assert t[0.0]["mean_envelope_size"] == 1.0 and t[0.0]["envelope_coverage"]["value"] == pytest.approx(2 / 3, abs=1e-3)
    assert t[2.0]["envelope_coverage"]["value"] == 1.0                     # 19 mm +/- 2 reaches LR-4
    assert t[3.0]["mean_envelope_size"] >= t[2.0]["mean_envelope_size"] >= t[1.0]["mean_envelope_size"]
    assert t[0.0]["alert_rate"]["value"] <= t[2.0]["alert_rate"]["value"]
    assert t[2.0]["near_cutoff_rate"]["value"] == pytest.approx(1 / 3, abs=1e-3)


def test_deferral_precision_and_recall():
    rows = [{"gold": "LR-M", "pred": "defer"}, {"gold": "LR-TIV", "pred": "LR-4"},
            {"gold": "LR-5", "pred": "defer"}, {"gold": "LR-3", "pred": "LR-3"}, {"gold": "LR-M", "pred": "LR-M"}]
    s = system_summary(rows)
    assert s["deferral_precision"]["k"] == 2 and s["deferral_precision"]["n"] == 3     # LR-M answer counts for B1
    assert s["deferral_recall"]["k"] == 2 and s["deferral_recall"]["n"] == 3


def test_per_source_breakdown(monkeypatch):
    from radsenvelope.evaluation import compare
    monkeypatch.setattr(compare, "llm_direct", lambda text: {"category": "LR-5", "contradiction": False, "seconds": 0,
                                                             "size_mm": 25, "engine_category": "LR-5", "error": None,
                                                             "features": {}})
    cases = [{"id": "RP1", "text": "25 mm observation with arterial phase hyperenhancement and washout.", "gold": "LR-5",
              "source": "radiopaedia"},
             {"id": "EPMC1", "text": "12 mm observation without arterial phase hyperenhancement.", "gold": "LR-3",
              "source": "europepmc"}]
    res = compare.run(cases, systems=("B1", "B2"))
    assert set(res["per_source"]) == {"radiopaedia", "europepmc"}
    assert res["per_source"]["europepmc"]["B1"]["accuracy"]["value"] == 0.0
    assert res["per_source"]["radiopaedia"]["B2"]["accuracy"]["value"] == 1.0
    assert res["B1"]["summary"]["accuracy"]["value"] == 0.5                 # pooled


def test_identical_share():
    a = [{"category": "LR-4", "envelope": ["LR-4"]}, {"category": "LR-3", "envelope": ["LR-3", "LR-4"]}]
    b = [{"category": "LR-4", "envelope": ["LR-4"]}, {"category": "LR-3", "envelope": ["LR-3"]}]
    assert identical_share([a, a, a]) == {"cases": 2, "identical": 2, "share": 1.0}
    assert identical_share([a, b]) == {"cases": 2, "identical": 1, "share": 0.5}


def test_annotation_status_single_reviewer():
    spec = importlib.util.spec_from_file_location("annotator_kappa", TOOLS / "annotator_kappa.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    empty = {"RP001": {"gold_aphe": ""}}
    one = {"RP001": {"gold_aphe": "present"}}
    assert tool.report(empty, empty)["status"] == "not yet collected (single reviewer)"
    assert tool.report(one, empty)["status"] == "not yet collected (single reviewer)"
    both = tool.report({"1": {"gold_aphe": "present"}, "2": {"gold_aphe": "absent"}},
                       {"1": {"gold_aphe": "present"}, "2": {"gold_aphe": "present"}},
                       {"systems": {"Ours": {"rows": [{"id": "1", "features": {"aphe": "present"}}]}}})
    assert both["status"] == "collected" and both["adjudicated_cases"] == 1
    assert both["extractor_f1_vs_adjudicated"]["Ours"]["aphe"]["accuracy"] == 1.0
