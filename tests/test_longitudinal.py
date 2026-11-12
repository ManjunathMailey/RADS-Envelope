"""Longitudinal reasoning: rule file, every branch of compare(), prior matching, merge policy, API."""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radsenvelope.api import app as appmod
from radsenvelope.engine.longitudinal import compare
from radsenvelope.engine.ruleset import RuleSet, RuleSetError, get_ruleset
from radsenvelope.generation.impression import verify
from radsenvelope.pipeline import Settings, analyse_report, match_prior

RS = get_ruleset()
LEX = Settings(extractor="lexicon")
S10 = json.loads((Path(__file__).resolve().parents[1] / "data" / "samples" / "longitudinal.json")
                 .read_text(encoding="utf-8"))[0]
client = TestClient(appmod.app)


def cmp(cur, prior, days=100, modality="MRI", tol=0.0):
    from datetime import date, timedelta
    d = date(2026, 11, 13)
    return compare(cur, d.isoformat(), prior, (d - timedelta(days=days)).isoformat(), modality, tol, RS)


# ---------- rule file ----------
def test_growth_section_values_come_from_yaml():
    g = RS.growth
    assert (g["threshold_percent"], g["threshold_max_days"], g["stability_min_days"]) == (50, 183, 730)
    assert g["valid_prior_modalities"] == ["CT", "MRI"] and g["unequivocal_change"] == "size_tolerance"


def test_missing_or_invalid_growth_section_is_rejected():
    raw = copy.deepcopy(RS.raw)
    del raw["growth"]
    with pytest.raises(RuleSetError, match="growth"):
        RuleSet(raw).validate()
    for key, bad in (("threshold_percent", 0), ("threshold_max_days", "six months"), ("valid_prior_modalities", []),
                     ("unequivocal_change", 1.0), ("stability_min_days", 100)):
        raw = copy.deepcopy(RS.raw)
        raw["growth"][key] = bad
        with pytest.raises(RuleSetError):
            RuleSet(raw).validate()


# ---------- compare(): thresholds and boundaries ----------
def test_exactly_50_percent_is_threshold_growth():
    r = cmp(15, 10, days=100)
    assert (r["growth_state"], r["rule"], r["percent_change"]) == ("present", "threshold_growth", 50.0)
    assert not r["af_malignant"] and not r["measurement_dependent"]


def test_just_below_50_percent_is_subthreshold():
    r = cmp(14.9, 10, days=100)
    assert (r["growth_state"], r["rule"], r["af_malignant"]) == ("absent", "subthreshold_growth", True)


def test_exactly_183_days_counts_and_184_does_not():
    assert cmp(20, 10, days=183)["growth_state"] == "present"
    r = cmp(20, 10, days=184)
    assert (r["growth_state"], r["rule"], r["af_malignant"]) == ("absent", "subthreshold_growth", True)
    assert "longer than 183 days" in r["explanation"]


def test_measurement_tolerance_makes_growth_uncertain():
    r = cmp(21, 13, days=122, tol=2.0)          # +62% point, +27% .. +109% across the tolerance
    assert (r["growth_state"], r["rule"], r["source"]) == ("uncertain", "threshold_growth_uncertain", "measurement")
    assert r["measurement_dependent"] and r["percent_range"] == [26.7, 109.1]
    assert not r["af_malignant"] and not r["af_benign"]


def test_threshold_met_at_every_end_is_present_with_tolerance():
    r = cmp(21, 10, days=123, tol=2.0)          # lowest end +58%
    assert r["growth_state"] == "present" and r["percent_range"][0] == 58.3


def test_threshold_met_at_no_end_is_absent():
    r = cmp(12, 10, days=100, tol=0.5)          # +20%, at most +31.6%
    assert r["growth_state"] == "absent" and r["percent_range"][1] < 50


def test_tiny_prior_does_not_divide_by_zero():
    r = cmp(5, 1.5, days=60, tol=2.0)           # prior - tol <= 0: upper end unbounded
    assert r["growth_state"] == "uncertain" and r["percent_range"][1] is None


# ---------- compare(): ancillary features ----------
def test_subthreshold_needs_change_larger_than_tolerance():
    assert cmp(22, 20, days=100, tol=2.0)["af_malignant"] is False          # +2 mm == tolerance: equivocal
    assert cmp(22.5, 20, days=100, tol=2.0)["af_malignant"] is True


def test_size_stability_boundary_at_730_days():
    r = cmp(21, 20, days=730, tol=2.0)
    assert (r["growth_state"], r["rule"], r["af_benign"]) == ("absent", "size_stability", True)
    assert cmp(21, 20, days=729, tol=2.0)["af_benign"] is False
    assert cmp(23, 20, days=800, tol=2.0)["af_benign"] is False             # changed by more than tolerance


def test_no_change_short_interval():
    r = cmp(20, 20, days=90, tol=2.0)
    assert (r["growth_state"], r["rule"], r["af_malignant"], r["af_benign"]) == ("absent", "no_threshold_growth", False, False)


# ---------- compare(): inputs that cannot be used ----------
def test_ultrasound_prior_cannot_be_used():
    for name in ("Ultrasound", "US", "ultrasound"):
        r = cmp(30, 10, modality=name)
        assert (r["growth_state"], r["rule"]) == ("not_documented", "prior_modality_invalid")
        assert "Ultrasound priors cannot be used for LI-RADS growth" in r["explanation"]
    assert cmp(30, 10, modality="MR")["growth_state"] == "present"
    assert cmp(30, 10, modality="ct")["growth_state"] == "present"


def test_invalid_interval_sizes_and_dates_never_raise():
    assert cmp(20, 10, days=0)["rule"] == "invalid_interval"
    assert cmp(20, 10, days=-5)["rule"] == "invalid_interval"
    assert cmp(None, 10)["rule"] == "missing_size" and cmp(20, None)["rule"] == "missing_size"
    r = compare(20, "13/11/2026", 10, "2026-07-01", "MRI", 2.0, RS)
    assert (r["growth_state"], r["rule"]) == ("not_documented", "invalid_date")


# ---------- matching ----------
def test_match_by_segment_then_order():
    assert match_prior(["Segment VI", "Segment II"], ["Segment II", "Segment VI"]) == [(1, "segment"), (0, "segment")]
    assert match_prior(["Observation 1", "Observation 2"], ["Observation 1", "Observation 2"]) == [(0, "order"), (1, "order")]
    assert match_prior(["Segment VI"], ["Observation 1"]) == [(0, "order")]
    assert match_prior(["Segment VI"], ["Segment II"]) == [(None, "none")]     # different segments never compared
    assert match_prior(["Segment VI", "Observation 2"], []) == [(None, "none"), (None, "none")]


# ---------- pipeline ----------
def test_s10_growth_from_prior_end_to_end():
    out = analyse_report(S10["report"], LEX, prior=S10["prior"])
    o = out["observations"][0]
    assert o["result"]["acr_category"] == "LR-5" and o["result"]["envelope"] == ["LR-5"]
    assert o["features"]["growth"] == "present" and o["extraction"]["growth"]["evidence"] == "From prior study"
    lg = o["longitudinal"]
    assert (lg["matching"], lg["prior_mm"], lg["current_mm"], lg["interval_days"]) == ("segment", 10.0, 21.0, 123)
    assert lg["rule"] == "threshold_growth" and lg["applied"] and lg["prior_conflict"] is None
    assert "Compared with prior MRI (2026-07-13): 10 -> 21 mm (+110% in 123 days), threshold growth." in out["impression"]
    assert out["consistency"]["consistent"] and o["grounding_errors"] == []


def test_s10_without_prior():
    out = analyse_report(S10["report"], LEX)
    r = out["observations"][0]["result"]
    assert r["acr_category"] == "LR-4" and r["envelope"] == ["LR-3", "LR-4", "LR-5"]
    assert "longitudinal" not in out["observations"][0] and "Compared with prior" not in out["impression"]


def test_explicit_report_statement_is_kept_and_conflict_flagged():
    report = "Segment VI: 21 mm observation with nonrim arterial phase hyperenhancement. Stable compared with the prior study."
    out = analyse_report(report, LEX, prior=S10["prior"])
    o = out["observations"][0]
    assert o["features"]["growth"] == "absent" and o["result"]["acr_category"] == "LR-4"
    assert o["longitudinal"]["growth_state"] == "present" and not o["longitudinal"]["applied"]
    assert "report's value is kept" in o["longitudinal"]["prior_conflict"]
    assert "the report's statement is used" in out["impression"] and out["consistency"]["consistent"]


def test_ultrasound_prior_leaves_growth_undocumented():
    prior = dict(S10["prior"], modality="Ultrasound")
    out = analyse_report(S10["report"], LEX, prior=prior)
    o = out["observations"][0]
    assert o["features"]["growth"] == "not_documented" and o["result"]["acr_category"] == "LR-4"
    assert o["longitudinal"]["rule"] == "prior_modality_invalid"
    assert "growth not assessed (Ultrasound priors cannot be used" in out["impression"]


def test_measurement_uncertain_growth_enters_the_envelope():
    prior = dict(S10["prior"], report="Segment VI: 13 mm observation.", prior_date="2026-07-14")
    o = analyse_report(S10["report"], LEX, prior=prior)["observations"][0]
    assert o["features"]["growth"] == "uncertain" and o["confidence"]["growth"]["source"] == "measurement"
    assert o["result"]["acr_category"] == "LR-4" and "LR-5" in o["result"]["envelope"]


def test_subthreshold_growth_sets_ancillary_feature():
    report = "Segment II: 14 mm observation without arterial phase hyperenhancement. No washout. No capsule."
    prior = {"report": "Segment II: 10 mm observation.", "prior_date": "2026-01-01", "current_date": "2026-11-13",
             "modality": "CT"}
    o = analyse_report(report, LEX, prior=prior)["observations"][0]
    assert o["longitudinal"]["rule"] == "subthreshold_growth" and o["features"]["af_malignant"] == "present"
    assert o["extraction"]["af_malignant"]["evidence"] == "From prior study"
    assert o["result"]["acr_category"] == "LR-4"          # LR-3 upgraded by one ancillary feature


def test_two_observations_matched_by_segment_out_of_order():
    report = ("Observation 1: Segment VI, 21 mm observation with nonrim arterial phase hyperenhancement. No washout.\n"
              "Observation 2: Segment II, 15 mm observation with nonrim arterial phase hyperenhancement. No washout.")
    prior = {"report": "Observation 1: Segment II, 14 mm observation.\nObservation 2: Segment VI, 10 mm observation.",
             "prior_date": "2026-07-13", "current_date": "2026-11-13", "modality": "MRI"}
    out = analyse_report(report, LEX, prior=prior)
    a, b = (o["longitudinal"] for o in out["observations"])
    assert (a["matching"], a["prior_mm"], a["rule"]) == ("segment", 10.0, "threshold_growth")
    assert (b["matching"], b["prior_mm"], b["rule"]) == ("segment", 14.0, "no_threshold_growth")
    assert out["impression"].count("Compared with prior") == 2 and out["consistency"]["consistent"]


def test_unmatched_observation_is_reported_not_compared():
    prior = dict(S10["prior"], report="Segment II: 10 mm observation.")
    o = analyse_report(S10["report"], LEX, prior=prior)["observations"][0]
    assert o["longitudinal"]["matching"] == "none" and o["features"]["growth"] == "not_documented"


def test_impression_consistent_with_longitudinal_lines_for_all_samples():
    samples = json.loads((Path(__file__).resolve().parents[1] / "data" / "samples" / "reports.json").read_text())
    for s in samples:
        out = analyse_report(s["report"], LEX, prior=S10["prior"])
        assert verify(out["impression"], out["observations"])["consistent"], s["id"]


# ---------- API ----------
def test_api_analyse_with_prior_and_validation():
    body = {"report": S10["report"], "extractor": "lexicon", "prior": S10["prior"]}
    out = client.post("/api/analyse", json=body).json()
    assert out["observations"][0]["result"]["acr_category"] == "LR-5" and out["prior"]["modality"] == "MRI"
    bad = client.post("/api/analyse", json={**body, "prior": {**S10["prior"], "prior_date": "13/07/2026"}})
    assert bad.status_code == 422 and "yyyy-mm-dd" in bad.text
    bad = client.post("/api/analyse", json={**body, "prior": {**S10["prior"], "current_date": "2026-02-30"}})
    assert bad.status_code == 422 and "current_date" in bad.text
    bad = client.post("/api/analyse", json={**body, "prior": {**S10["prior"], "modality": "PET"}})
    assert bad.status_code == 422 and "CT, MRI or Ultrasound" in bad.text
    ok = client.post("/api/analyse", json={**body, "prior": {**S10["prior"], "current_date": None, "modality": "us"}})
    assert ok.status_code == 200 and ok.json()["observations"][0]["longitudinal"]["prior_modality"] == "Ultrasound"


def test_api_recompute_preserves_longitudinal():
    o = client.post("/api/analyse", json={"report": S10["report"], "extractor": "lexicon", "prior": S10["prior"]}).json()["observations"][0]
    feats = dict(o["features"], washout="present")
    body = {"observations": [{"label": o["label"], "features": feats, "size_mm": o["size_mm"],
                              "size_tolerance_mm": 2, "longitudinal": o["longitudinal"]}]}
    out = client.post("/api/recompute", json=body).json()
    assert out["observations"][0]["longitudinal"] == o["longitudinal"]
    assert "Compared with prior MRI" in out["impression"] and out["consistency"]["consistent"]


def test_api_samples_unchanged_and_longitudinal_sample_served():
    assert len(client.get("/api/samples").json()) == 9
    assert [s["id"] for s in client.get("/api/samples/longitudinal").json()] == ["S10"]
