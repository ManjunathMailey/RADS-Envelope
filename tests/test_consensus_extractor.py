"""Pre-registered consensus: the lexicon as a second extractor in the consensus step."""
import pytest

import radsenvelope.pipeline as pipe
from radsenvelope.evaluation import compare
from radsenvelope.extraction import consensus
from radsenvelope.extraction.consensus import EXTRACTOR_DISAGREEMENT, combine_extractors
from radsenvelope.extraction.schema import Extraction
from radsenvelope.pipeline import Settings, analyse_report

FEATS = ("aphe", "washout", "capsule", "growth", "af_malignant", "af_benign")


def _ex(size=18.0, ev="", **states):
    d = {"size_mm": size, "size_evidence": f"{size} mm" if size else ""}
    for k in FEATS:
        st = states.get(k, "not_documented")
        d[k] = {"state": st, "evidence": ev if st != "not_documented" else ""}
    return Extraction.model_validate(d)


def _conf():
    return {**{k: {"source": None} for k in FEATS}, "size": {"values": [18.0], "spread_mm": 0.0, "agreement": 1.0}}


def test_agreement_keeps_value_and_abstain_is_no_vote():
    llm, lex = _ex(aphe="present", washout="absent"), _ex(aphe="present", washout="not_documented")
    ex, conf = combine_extractors(llm, _conf(), lex)
    assert ex.aphe.state == "present" and ex.washout.state == "absent"       # agree / lexicon abstains
    assert conf["aphe"]["source"] is None and conf["washout"]["second_extractor"] == "not_documented"


def test_disagreement_becomes_uncertain_with_source():
    ex, conf = combine_extractors(_ex(washout="present", ev="fades to background"), _conf(), _ex(washout="absent"))
    assert ex.washout.state == "uncertain" and ex.washout.evidence == "fades to background"
    assert conf["washout"]["source"] == EXTRACTOR_DISAGREEMENT
    assert conf["washout"]["disagreement"] == {"llm": "present", "lexicon": "absent"}
    ex, conf = combine_extractors(_ex(growth="not_documented"), _conf(), _ex(growth="present"))
    assert ex.growth.state == "uncertain"                                    # the lexicon reads what the LLM missed


def test_size_widening_and_fill():
    ex, conf = combine_extractors(_ex(size=19.0), _conf(), _ex(size=21.0))
    assert ex.size_mm == 19.0 and conf["size"]["spread_mm"] == 4.0          # 2 + 4/2 = 4 mm reaches 21 mm
    assert conf["size"]["second_extractor_mm"] == 21.0
    ex, conf = combine_extractors(_ex(size=None), _conf(), _ex(size=21.0))
    assert ex.size_mm == 21.0 and conf["size"]["spread_mm"] == 0.0
    ex, conf = combine_extractors(_ex(size=19.0), _conf(), _ex(size=19.0))
    assert conf["size"]["spread_mm"] == 0.0


def test_pipeline_consensus_mode(monkeypatch):
    monkeypatch.setattr(pipe.llm, "available", lambda *a: (True, "test-model"))
    monkeypatch.setattr(pipe.llm, "extract", lambda text, *a: (_ex(size=20.0, aphe="present", washout="present"), 0.01))
    text = "Segment VI: 20 mm observation with arterial phase hyperenhancement. On the portal venous phase it fades to background; no washout."
    out = analyse_report(text, Settings(extractor="consensus"))
    o = out["observations"][0]
    assert o["features"]["washout"] == "uncertain" and o["confidence"]["washout"]["source"] == EXTRACTOR_DISAGREEMENT
    assert "lexicon consensus" in out["extractor"]["used"] and out["extractor"]["disagreements"] == ["washout"]
    assert o["result"]["acr_category"] == "LR-4" and "LR-5" in o["result"]["envelope"] and out["consistency"]["consistent"]


def test_consensus_falls_back_to_lexicon_without_llm(monkeypatch):
    monkeypatch.setattr(pipe.llm, "available", lambda *a: (False, "offline"))
    out = analyse_report("Segment VI: 25 mm observation with arterial phase hyperenhancement and washout.",
                         Settings(extractor="consensus"))
    assert out["extractor"]["used"].startswith("Lexicon") and out["extractor"]["requested"] == "consensus"


def test_derived_consensus_row_matches_pipeline_combination():
    llm_row = {"id": "x", "gold": "LR-4", "features": {"aphe": "present", "washout": "present", "capsule": "absent",
               "growth": "not_documented", "af_malignant": "not_documented", "af_benign": "not_documented"},
               "evidence": {"washout": "fades"}, "size_mm": 22.0, "size_evidence": "22 mm", "size_tolerance_mm": 2.0,
               "defer_reasons": [], "seconds": 1.0}
    lex_row = {**llm_row, "features": {**llm_row["features"], "washout": "absent"}, "evidence": {}, "seconds": 0.0}
    r = compare.consensus_row(llm_row, lex_row)
    assert r["features"]["washout"] == "uncertain" and r["disagreements"] == ["washout"]
    assert r["pred"] == "LR-4" and r["envelope"] == ["LR-4", "LR-5"] and r["consistent"]


def test_add_consensus_keeps_other_arms_unchanged():
    rows = lambda pred: [{"id": "a", "gold": "LR-5", "pred": pred, "features": {"aphe": "present", "washout": "present"},
                          "evidence": {}, "size_mm": 25.0, "size_evidence": "25 mm", "size_tolerance_mm": 2.0,
                          "defer_reasons": [], "envelope": [pred], "critical": False, "contradiction": False,
                          "consistent": True, "seconds": 0, "any_unresolved": False}]
    res = {"systems": {s: {"summary": {"marker": s}, "rows": rows("LR-5")} for s in ("B2", "B3", "Ours")}}
    out = compare.add_consensus(res)
    assert out["systems"]["B2"] == res["systems"]["B2"] and out["systems"]["Ours"] == res["systems"]["Ours"]
    assert out["systems"]["OursC"]["summary"]["accuracy"]["value"] == 1.0 and out["consensus_added"]
