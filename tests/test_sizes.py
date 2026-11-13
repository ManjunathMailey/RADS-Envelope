"""Size integrity guard: parsing written sizes and correcting extractor sizes that the report does not state."""
import pytest

import radsenvelope.pipeline as pipe
from radsenvelope.extraction.schema import Extraction
from radsenvelope.extraction.sizes import parse_sizes, reconcile_size
from radsenvelope.pipeline import Settings, analyse_report


@pytest.mark.parametrize("text,mm", [
    ("9.5 mm", 9.5), ("2.5 cm", 25.0), ("2,5 cm", 25.0), ("1.2 x 0.9 cm", 12.0), ("1.2x0.9cm", 12.0),
    ("18mm", 18.0), ("18-mm observation", 18.0), ("12 by 9 mm", 12.0), ("a 95 mm mass", 95.0), ("4 centimetres", 40.0),
])
def test_parse_sizes(text, mm):
    assert [s["mm"] for s in parse_sizes(text)] == [mm]


@pytest.mark.parametrize("text,mm", [
    ("Target-HCC No.: 3; HCC Size (mm): 11.6; APHE: Yes", 11.6),
    ("Size (cm): 2.1", 21.0),
    ("diameter, mm: 18", 18.0),
    ("Lesion size [mm]: 12 x 9", 12.0),
    ("Maximum diameter (cm) = 1,5", 15.0),
])
def test_parse_unit_from_label_or_column_header(text, mm):
    assert [s["mm"] for s in parse_sizes(text)] == [mm]


def test_label_units_do_not_double_count_or_invent_units():
    assert [s["mm"] for s in parse_sizes("Size (mm): 18 mm")] == [18.0]         # unit after the number wins, once
    for text in ("Size (in): 2", "Size (HU): 40", "Size: 12", "Patients No.: 1; Child-Pugh Grade: A",
                 "Segment (mm) 8 and age 64"):
        assert parse_sizes(text) == [], text
    s = parse_sizes("HCC Size (mm): 11.6")[0]
    assert "HCC Size (mm): 11.6"[s["span"][0]:s["span"][1]] == "11.6"              # the value is verbatim


def test_guard_accepts_table_size_and_still_rejects_misreads():
    row = "Patients No.: 1; HCC Size (mm): 11.6; APHE: Yes; Enhancing Capsule: No"
    assert reconcile_size(11.6, "11.6", row) == (11.6, "11.6", False)
    assert reconcile_size(116, "", row)[0] == 11.6                                   # dropped decimal still corrected
    assert reconcile_size(None, "", row)[0] == 11.6                                  # filled from the labelled value
    assert reconcile_size(95, "9.5 mm", "Segment II: 9.5 mm observation") == (9.5, "9.5 mm", True)


def test_parse_ignores_numbers_without_unit_and_keeps_order():
    assert parse_sizes("Segment 4a: 3 nodules, T2 hyperintense, 2 phases.") == []
    assert [s["mm"] for s in parse_sizes("increased from 15 mm to 43 mm")] == [15.0, 43.0]
    s = parse_sizes("Segment VI: 9.5 mm observation")[0]
    assert s["text"] == "9.5 mm" and "Segment VI: 9.5 mm observation"[s["span"][0]:s["span"][1]] == "9.5 mm"


def test_reconcile_rules():
    assert reconcile_size(95, "9.5 mm", "Segment II: 9.5 mm observation") == (9.5, "9.5 mm", True)
    assert reconcile_size(95, "", "Segment II: a 95 mm observation") == (95, "", False)            # really 95
    assert reconcile_size(250, "", "Segment VII: 2.5 cm observation") == (25.0, "2.5 cm", True)    # from text
    assert reconcile_size(18, "", "Segment VI: small observation") == (None, "", True)             # no unit: null
    assert reconcile_size(None, "", "small observation") == (None, "", False)
    assert reconcile_size(12.004, "", "1.2 x 0.9 cm") == (12.004, "", False)                       # within 0.01


def _fake(size, evidence=""):
    d = {"size_mm": size, "size_evidence": evidence}
    for k in ("aphe", "washout", "capsule", "growth", "af_malignant", "af_benign"):
        d[k] = {"state": "present" if k == "aphe" else "not_documented", "evidence": ""}
    return Extraction.model_validate(d)


@pytest.fixture
def mocked_llm(monkeypatch):
    """An LLM that drops the decimal point: '9.5 mm' -> 95, and reads 15 mm correctly."""
    monkeypatch.setattr(pipe.llm, "available", lambda *a: (True, "test-model"))

    def extract(text, *a):
        return (_fake(95.0, "9.5 mm") if "9.5" in text else _fake(15.0, "15 mm")), 0.01

    monkeypatch.setattr(pipe.llm, "extract", extract)
    monkeypatch.setattr(pipe.llm, "sample", lambda text, k: ([extract(text)[0], _fake(9.5, "9.5 mm"), extract(text)[0]], 0.03))


def test_mocked_llm_95_is_corrected_to_9_5(mocked_llm):
    out = analyse_report("Segment VI: 9.5 mm observation with nonrim arterial phase hyperenhancement.",
                         Settings(extractor="llm"))
    o = out["observations"][0]
    assert o["size_mm"] == 9.5 and o["confidence"]["size"]["corrected_from"] == 95.0
    assert o["result"]["acr_category"] == "LR-3" and o["result"]["trace"][1]["value"].startswith("9.5 mm")


def test_guard_runs_before_consensus(mocked_llm):
    o = analyse_report("Segment VI: 9.5 mm observation.", Settings(extractor="llm", samples=3))["observations"][0]
    assert o["size_mm"] == 9.5 and o["confidence"]["size"]["spread_mm"] == 0.0
    assert o["confidence"]["size"]["corrected_values"] == [95.0, 95.0]


def test_prior_size_is_guarded_too(mocked_llm):
    prior = {"report": "Segment VI: 9.5 mm observation.", "prior_date": "2026-08-01",
             "current_date": "2026-11-13", "modality": "MRI"}
    lg = analyse_report("Segment VI: 15 mm observation.", Settings(extractor="llm"), prior=prior)["observations"][0]["longitudinal"]
    assert lg["prior_mm"] == 9.5 and lg["prior_size_corrected_from"] == 95.0
    assert lg["percent_change"] == 57.9


def test_lexicon_sizes_unchanged_and_comma_decimal_fixed():
    o = analyse_report("Segment VI: 18 mm observation.", Settings(extractor="lexicon"))["observations"][0]
    assert o["size_mm"] == 18.0 and "corrected_from" not in o["confidence"]["size"]
    o = analyse_report("Segment VII: 2,5 cm observation.", Settings(extractor="lexicon"))["observations"][0]
    assert o["size_mm"] == 25.0
