"""Impression generation is consistent with the engine for every input; pipeline end to end."""
import json
from itertools import product
from pathlib import Path

from radsenvelope.engine.envelope import STATES
from radsenvelope.generation.impression import generate, verify
from radsenvelope.pipeline import Settings, analyse_report, run_observation

SAMPLES = json.loads((Path(__file__).resolve().parents[1] / "data" / "samples" / "reports.json").read_text())


def test_impression_consistent_for_all_state_combinations():
    for combo in product(STATES, repeat=4):
        feats = dict(zip(("aphe", "washout", "capsule", "growth"), combo))
        feats.update(af_malignant="not_documented", af_benign="not_documented")
        for size in (8, 19, 27):
            res = run_observation("Segment VI", feats, size, 2.0, True, [])
            obs = [{"label": "Segment VI", "size_mm": size, "features": feats, "result": res}]
            text = generate(obs)
            assert verify(text, obs)["consistent"], (combo, size, text)
            assert f"LI-RADS {res['acr_category'][-1]}" in text


def test_impression_for_deferred_and_unassignable():
    feats = {k: "absent" for k in ("aphe", "washout", "capsule", "growth", "af_malignant", "af_benign")}
    deferred = run_observation("Segment IV", feats, 30, 2.0, True, ["Rim APHE suggests LR-M"])
    missing = run_observation("Segment VI", feats, None, 2.0, True, [])
    obs = [{"label": "Segment IV", "size_mm": 30, "features": feats, "result": deferred},
           {"label": "Segment VI", "size_mm": None, "features": feats, "result": missing}]
    text = generate(obs)
    assert "not assigned automatically" in text and verify(text, obs)["consistent"]


EXPECTED = {"S1": ("LR-3", True), "S2": ("LR-5", False), "S3": ("LR-3", True), "S4": ("LR-5", False),
            "S5": ("LR-3", False), "S6": (None, False), "S7": ("LR-5", False), "S8": (None, False),
            "S9": ("LR-3", True)}


def test_pipeline_on_samples_with_lexicon():
    for s in SAMPLES:
        out = analyse_report(s["report"], Settings(extractor="lexicon"))
        r = out["observations"][0]["result"]
        cat, critical = EXPECTED[s["id"]]
        assert r.get("acr_category") == cat, s["id"]
        assert bool(r.get("decision_critical")) == critical, s["id"]
        assert out["consistency"]["consistent"]


def test_pipeline_multi_observation_audit():
    report = ("Observation 1: Segment VI, 18 mm observation with nonrim arterial phase hyperenhancement. "
              "Possible subtle washout. No capsule.\n"
              "Observation 2: Segment II, 25 mm observation with arterial phase hyperenhancement, "
              "nonperipheral washout and enhancing capsule.\nImpression: 1. LR-3. 2. LR-4.")
    out = analyse_report(report, Settings(extractor="lexicon"))
    assert [o["label"] for o in out["observations"]] == ["Segment VI", "Segment II"]
    assert out["observations"][1]["audit"]["contradiction"] is True
    assert out["exam"]["highest_category"] == "LR-5"
