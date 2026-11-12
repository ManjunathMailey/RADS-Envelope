"""Evaluation protocol: dev/test split, the test-run guard, prompt hashes in results."""
import importlib.util
import json
from pathlib import Path

import pytest

from radsenvelope.evaluation import real_cases
from radsenvelope.extraction import llm

TOOLS = Path(__file__).resolve().parents[1] / "data_tools"
spec = importlib.util.spec_from_file_location("split_real", TOOLS / "split_real.py")
split_real = importlib.util.module_from_spec(spec)
spec.loader.exec_module(split_real)


def _rows():
    rows = [{"id": i, "url": "", "radiologist_category": c} for i, c in
            [("RP001", "LR-3"), ("RP002", "LR-5"), ("RP003", "LR-M"), ("PMC001", "LR-5"), ("PMC002", "LR-3")]]
    rows += [{"id": f"RP{n:03d}", "url": "", "radiologist_category": "LR-5" if n % 2 else "LR-4"} for n in range(10, 40)]
    rows += [{"id": f"EPMC{n:03d}", "url": f"https://europepmc.org/article/PMC/PMC{900000 + n}",
              "radiologist_category": ["LR-5", "LR-4", "LR-3", "LR-M"][n % 4]} for n in range(1, 41)]
    rows.append({"id": "EPMC099", "url": "https://europepmc.org/article/PMC/PMC8122342", "radiologist_category": "LR-5"})
    return rows


def test_forced_dev_cases_never_in_test():
    split = split_real.make_split(_rows())
    by_id = {r["id"]: r for r in split}
    for case_id in split_real.FORCED_DEV:
        assert by_id[case_id]["split"] == "dev" and by_id[case_id]["forced_dev_reason"]
    assert by_id["EPMC099"]["split"] == "dev" and "harvester" in by_id["EPMC099"]["forced_dev_reason"]


def test_split_is_deterministic_stratified_and_about_40_60():
    a, b = split_real.make_split(_rows()), split_real.make_split(list(reversed(_rows())))
    assert a == b                                                    # order-independent, fixed seed
    assert split_real.test_ids_sha256(a) == split_real.test_ids_sha256(b)
    assert split_real.make_split(_rows(), seed=1) != a               # the seed matters
    free = [r for r in a if not r["forced_dev_reason"]]
    dev_share = sum(r["split"] == "dev" for r in a) / len(a)
    assert 0.35 <= dev_share <= 0.5 and any(r["split"] == "test" for r in free)
    for source in ("radiopaedia", "europepmc"):
        cats = {r["category"] for r in a if r["source"] == source and r["split"] == "test"}
        assert len(cats) >= 2                                        # every source keeps several categories in test
    assert {r["source"] for r in a} == {"radiopaedia", "pmc", "europepmc"}


def test_test_run_guard():
    split = {"RP001": "dev", "X": "test"}
    real_cases.check_test_allowed("dev", split, {})                  # dev is always allowed
    with pytest.raises(SystemExit, match="RADS_RUN_TEST"):
        real_cases.check_test_allowed("test", split, {})
    with pytest.raises(SystemExit, match="RADS_RUN_TEST"):
        real_cases.check_test_allowed("all", split, {})              # all includes held-out cases
    real_cases.check_test_allowed("test", split, {"RADS_RUN_TEST": "1"})
    with pytest.raises(SystemExit, match="No test split"):
        real_cases.check_test_allowed("test", None, {"RADS_RUN_TEST": "1"})


def test_select_split_before_and_after_freeze():
    rows = [{"id": "RP001"}, {"id": "X"}]
    assert real_cases.select_split(rows, "dev", None) == rows and real_cases.select_split(rows, "test", None) == []
    split = {"RP001": "dev", "X": "test"}
    assert real_cases.select_split(rows, "test", split) == [{"id": "X"}]


def test_test_runs_are_logged(tmp_path):
    log = tmp_path / "test_runs.log"
    real_cases.log_test_run("test", {"compare": True}, log)
    entry = json.loads(log.read_text().strip())
    assert entry["split"] == "test" and len(entry["prompt_hash"]) == 64 and "commit" in entry["git"]


def test_prompt_hash_tracks_prompt_and_model():
    h = llm.prompt_hash()
    assert len(h) == 64 and h == llm.prompt_hash(llm.SYSTEM, llm.MODEL)
    assert llm.prompt_hash(llm.SYSTEM + " ") != h and llm.prompt_hash(model="other-model") != h


ea_spec = importlib.util.spec_from_file_location("error_analysis", TOOLS / "error_analysis.py")
error_analysis = importlib.util.module_from_spec(ea_spec)
ea_spec.loader.exec_module(error_analysis)


def _row(gold, pred, size=29.0, **feats):
    base = {"aphe": "absent", "washout": "absent", "capsule": "absent", "growth": "absent",
            "af_malignant": "not_documented", "af_benign": "not_documented"}
    return {"id": "X", "gold": gold, "pred": pred, "size_mm": size, "features": {**base, **feats},
            "envelope": [pred], "evidence": {"growth": "ultrasound showed growth"}}


def test_error_analysis_classes():
    e = error_analysis.classify(_row("LR-3", "LR-4", growth="present"), "29 mm nodule")
    assert e["class"] == "extraction_error" and any(f["feature"] == "growth" and f["needed"] == "absent"
                                                    for f in e["features"])
    assert error_analysis.classify(_row("LR-M", "LR-4"), "")["class"] == "scope_error"
    assert error_analysis.classify(_row("LR-4", "defer"), "")["class"] == "scope_error"
    assert error_analysis.classify(_row("LR-3", "not_assignable", size=None), "small nodule")["class"] == "out_of_scope"
    assert error_analysis.classify(_row("LR-3", "not_assignable", size=None), "a 12 mm nodule")["class"] == "size_error"
    assert error_analysis.classify(_row("LR-4", "LR-3", size=19.5, aphe="present"), "19.5 mm")["class"] in (
        "size_error", "extraction_error")
    with pytest.raises(SystemExit, match="development split only"):
        error_analysis.analyse({"split": "test", "systems": {"Ours": {"rows": []}}}, {})


def test_results_carry_prompt_hash():
    rows = [{"id": "R1", "findings_text": "25 mm observation with arterial phase hyperenhancement and washout.",
             "radiologist_category": "LR-5"}]
    res = real_cases.evaluate(rows, "lexicon")
    assert res["prompt_hash"] == llm.prompt_hash() and res["b1_prompt_hash"] != res["prompt_hash"]
