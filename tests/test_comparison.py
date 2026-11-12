"""Comparison metrics (kappa, Wilson CI, confusion matrix), the LLM-direct baseline (mocked) and the runner."""
import importlib.util
import json
import random
from pathlib import Path

import pytest

from radsenvelope.evaluation import baselines, compare, real_cases
from radsenvelope.evaluation.metrics import (KAPPA_LABELS, cohen_kappa, confusion_matrix, system_summary,
                                             wilson)


def _expand(table):
    """2x2 agreement table [[yes/yes, yes/no], [no/yes, no/no]] -> two rating lists."""
    a, b = [], []
    for i, row in enumerate(table):
        for j, count in enumerate(row):
            a += [i] * count
            b += [j] * count
    return a, b


# ---------- kappa ----------
def test_kappa_textbook_2x2():
    # 50 items: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no -> po 0.70, pe 0.50, kappa 0.40
    a, b = _expand([[20, 5], [10, 15]])
    assert cohen_kappa(a, b, [0, 1]) == 0.4
    # 100 items: 45, 15, 25, 15 -> po 0.60, pe 0.54, kappa 0.1304
    a, b = _expand([[45, 15], [25, 15]])
    assert cohen_kappa(a, b, [0, 1]) == 0.1304
    assert cohen_kappa(a, b, [0, 1], "quadratic") == 0.1304            # two categories: weights reduce to 0/1


def test_quadratic_kappa_matches_closed_form():
    """Quadratic-weighted kappa = 1 - n * sum (a_i - b_i)^2 / sum_i sum_j (a_i - b_j)^2."""
    rng = random.Random(3)
    for _ in range(20):
        a = [rng.randint(2, 5) for _ in range(40)]
        b = [min(5, max(2, x + rng.choice([-1, 0, 0, 1, 2]))) for x in a]
        n = len(a)
        closed = 1 - n * sum((x - y) ** 2 for x, y in zip(a, b)) / sum((x - y) ** 2 for x in a for y in b)
        labels = [f"LR-{x}" for x in a], [f"LR-{y}" for y in b]
        assert cohen_kappa(*labels, KAPPA_LABELS, "quadratic") == pytest.approx(closed, abs=1e-4)


def test_kappa_edge_cases():
    assert cohen_kappa(["LR-3", "LR-4"], ["LR-3", "LR-4"], KAPPA_LABELS, "quadratic") == 1.0
    assert cohen_kappa(["LR-3"] * 4, ["LR-3"] * 4, KAPPA_LABELS) is None              # no expected disagreement
    assert cohen_kappa([], [], KAPPA_LABELS) is None
    # LR-M is ignored; the single remaining pair (LR-3 vs LR-4) has observed == expected disagreement
    assert cohen_kappa(["LR-3", "LR-M"], ["LR-4", "LR-M"], KAPPA_LABELS, "quadratic") == 0.0


# ---------- Wilson ----------
def test_wilson_known_values():
    assert wilson(8, 10) == [0.4902, 0.9433]
    assert wilson(0, 10) == [0.0, 0.2775]
    assert wilson(10, 10) == [0.7225, 1.0]
    assert wilson(0, 0) is None


# ---------- confusion matrix and summary ----------
def test_confusion_matrix_with_other_bucket():
    cm = confusion_matrix(["LR-3", "LR-5", "LR-5", "LR-4"], ["LR-3", "LR-5", "defer", "LR-5"])
    assert cm["labels"] == ["LR-2", "LR-3", "LR-4", "LR-5", "other"]
    m = cm["matrix"]
    assert m[1][1] == 1 and m[3][3] == 1 and m[3][4] == 1 and m[2][3] == 1 and sum(map(sum, m)) == 4


def test_system_summary():
    rows = [{"gold": "LR-5", "pred": "LR-5", "envelope": ["LR-5"], "critical": False, "contradiction": False, "consistent": True},
            {"gold": "LR-5", "pred": "LR-4", "envelope": ["LR-4", "LR-5"], "critical": True, "contradiction": False, "consistent": True},
            {"gold": "LR-3", "pred": "LR-3", "envelope": ["LR-3"], "critical": False, "contradiction": False, "consistent": True},
            {"gold": "LR-3", "pred": "not_assignable", "envelope": None, "critical": False, "contradiction": False, "consistent": True},
            {"gold": "LR-M", "pred": "defer", "envelope": None, "critical": False, "contradiction": False, "consistent": True}]
    s = system_summary(rows, envelope=True)
    assert s["graded"] == 4 and s["accuracy"]["value"] == 0.5
    assert s["lr5_sensitivity"]["value"] == 0.5 and s["lr5_specificity"]["value"] == 1.0
    assert s["envelope_coverage"]["value"] == 0.75 and s["mean_envelope_size"] == pytest.approx(4 / 3, abs=1e-3)
    assert s["pm1_band_coverage"]["value"] == 0.75                 # unassigned prediction cannot cover
    assert s["contradiction_rate"]["value"] == 0.0 and s["correct_deferrals"]["value"] == 1.0
    assert s["alert_rate"]["value"] == 0.2 and s["accuracy"]["ci95"] == wilson(2, 4)


# ---------- B1 LLM-direct (LLM mocked) ----------
def _answer(category, size=15, **states):
    d = {"size_mm": size, "size_evidence": f"{size} mm", "category": category}
    for k in ("aphe", "washout", "capsule", "growth", "af_malignant", "af_benign"):
        d[k] = {"state": states.get(k, "absent" if not k.startswith("af_") else "not_documented"), "evidence": ""}
    return json.dumps(d)


def test_llm_direct_parsing_and_contradiction(monkeypatch):
    monkeypatch.setattr(baselines, "_chat", lambda text, model: _answer("LR-5", aphe="present"))   # engine: LR-3
    d = baselines.llm_direct("Segment VI: 15 mm observation with APHE.")
    assert d["category"] == "LR-5" and d["engine_category"] == "LR-3" and d["contradiction"] is True
    monkeypatch.setattr(baselines, "_chat", lambda text, model: _answer("LR-5", aphe="present", washout="present"))
    assert baselines.llm_direct("x")["contradiction"] is False
    monkeypatch.setattr(baselines, "_chat", lambda text, model: _answer("LR-M", aphe="present"))
    assert baselines.llm_direct("x")["contradiction"] is None                  # not comparable
    monkeypatch.setattr(baselines, "_chat", lambda text, model: _answer("LR-4", size=None, aphe="present"))
    assert baselines.llm_direct("x")["contradiction"] is None                  # engine cannot assign without size


def test_llm_direct_handles_bad_output(monkeypatch):
    monkeypatch.setattr(baselines, "_chat", lambda text, model: '{"category": "LR-9"}')
    d = baselines.llm_direct("x")
    assert d["category"] is None and d["error"].startswith("unparseable")
    def boom(text, model):
        raise ConnectionError("offline")
    monkeypatch.setattr(baselines, "_chat", boom)
    assert baselines.llm_direct("x")["error"].startswith("LLM call failed")


def test_direct_prompt_allows_a_category():
    assert "Never assign a LI-RADS category." not in baselines.SYSTEM_DIRECT
    assert "LR-5" in baselines.SYSTEM_DIRECT and "category" in baselines.DirectAnswer.model_json_schema()["properties"]


# ---------- runner ----------
def test_compare_runner_with_mocked_llm(monkeypatch):
    import radsenvelope.pipeline as pipe
    from radsenvelope.extraction import lexicon
    monkeypatch.setattr(pipe.llm, "available", lambda *a: (True, "test-model"))
    monkeypatch.setattr(pipe.llm, "extract", lambda text, *a: (lexicon.extract(text), 0.01))
    monkeypatch.setattr(baselines, "_chat", lambda text, model: _answer("LR-5", size=25, aphe="present", washout="present"))
    cases = [{"id": "c1", "text": "Segment VI: 25 mm observation with arterial phase hyperenhancement and washout.",
              "gold": "LR-5", "gold_features": {"aphe": "present", "washout": "present"}, "gold_size_mm": 25.0},
             {"id": "c2", "text": "Segment II: 18 mm observation with arterial phase hyperenhancement. Possible washout.",
              "gold": "LR-3", "gold_features": {}, "gold_size_mm": None}]
    res = compare.run(cases)
    assert set(res) == {"B1", "B2", "B3", "Ours"}
    assert res["B2"]["summary"]["accuracy"]["value"] == 1.0 and res["B3"]["summary"]["accuracy"]["value"] == 1.0
    assert res["B1"]["summary"]["accuracy"]["value"] == 0.5 and res["B1"]["summary"]["contradiction_rate"]["value"] == 0.0
    ours = res["Ours"]["summary"]
    assert ours["envelope_coverage"]["value"] == 1.0 and ours["alert_rate"]["value"] == 0.5
    assert ours["consistency_verified"]["value"] == 1.0 and ours["features_n"] == 1
    assert ours["size_accuracy"]["value"] == 1.0 and "envelope_coverage" not in res["B3"]["summary"]
    assert [t["system"] for t in compare.table(res)] == ["B1", "B2", "B3", "Ours"]


def test_real_case_gold_columns():
    row = {"gold_aphe": "Present", "gold_washout": "not documented", "gold_capsule": "", "gold_growth": "maybe",
           "gold_size_mm": "26"}
    assert real_cases.gold_features(row) == {"aphe": "present", "washout": "not_documented"}
    assert real_cases.gold_size(row) == 26.0 and real_cases.gold_size({"gold_size_mm": ""}) is None


def test_annotator_kappa_tool(tmp_path):
    spec = importlib.util.spec_from_file_location("annotator_kappa",
                                                  Path(__file__).resolve().parents[1] / "data_tools" / "annotator_kappa.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    a = {"1": {"gold_aphe": "present", "gold_size_mm": "20", "radiologist_category": "LR-5"},
         "2": {"gold_aphe": "absent", "gold_size_mm": "12", "radiologist_category": "LR-3"},
         "3": {"gold_aphe": "present", "gold_size_mm": "", "radiologist_category": "LR-4"}}
    b = {"1": {"gold_aphe": "present", "gold_size_mm": "20.5", "radiologist_category": "LR-5"},
         "2": {"gold_aphe": "absent", "gold_size_mm": "15", "radiologist_category": "LR-3"},
         "3": {"gold_aphe": "absent", "gold_size_mm": "9", "radiologist_category": "LR-4"}}
    out = tool.agreement(a, b)
    assert out["matched_ids"] == 3 and out["features"]["aphe"]["n"] == 3
    assert out["features"]["aphe"]["kappa"] == cohen_kappa(["present", "absent", "present"], ["present", "absent", "absent"],
                                                           ("present", "absent", "uncertain", "not_documented"))
    assert out["size"] == {"n": 2, "within_1mm": 0.5, "mean_abs_diff_mm": 1.75}
    assert out["category"]["weighted_kappa"] == 1.0
