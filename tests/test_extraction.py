"""Segmentation, lexicon extractor, self-consistency consensus, grounding, scope guard."""
import json
from pathlib import Path

from radsenvelope.extraction import consensus, lexicon
from radsenvelope.extraction.schema import Extraction, Feature, grounding_errors, is_grounded
from radsenvelope.extraction.scope import defer_reasons
from radsenvelope.extraction.segment import split_observations, split_sections, stated_categories

SAMPLES = json.loads((Path(__file__).resolve().parents[1] / "data" / "samples" / "reports.json").read_text())


def test_sections_and_stated_categories():
    findings, imp = split_sections("Segment VI: 18 mm observation.\nImpression: LI-RADS 3.")
    assert findings.startswith("Segment VI") and stated_categories(imp) == ["LR-3"]


def test_multi_observation_split():
    text = ("Observation 1: Segment VI, 18 mm observation with APHE.\n"
            "Observation 2: Segment II, 25 mm observation with washout.")
    segs = split_observations(text)
    assert [s.label for s in segs] == ["Segment VI", "Segment II"]
    numbered = split_observations("1. 12 mm lesion in segment V.\n2. 30 mm lesion in segment VIII.")
    assert len(numbered) == 2 and numbered[1].label == "Segment VIII"
    assert len(split_observations("Segment VI: 18 mm observation. No washout.")) == 1


def test_lexicon_on_samples():
    expected = {
        "S1": {"aphe": "present", "washout": "uncertain", "capsule": "absent", "growth": "not_documented"},
        "S2": {"aphe": "present", "washout": "present", "capsule": "present", "growth": "absent"},
        "S6": {"aphe": "absent", "washout": "absent"},
        "S7": {"aphe": "present", "growth": "present"},
    }
    for s in SAMPLES:
        if s["id"] in expected:
            got = lexicon.extract(split_sections(s["report"])[0]).states()
            for k, v in expected[s["id"]].items():
                assert got[k] == v, (s["id"], k, got[k])
    assert lexicon.extract("small observation with washout").size_mm is None
    assert lexicon.extract("2.5 cm observation").size_mm == 25


def _ex(**states):
    base = {k: Feature(state="absent", evidence="") for k in
            ("aphe", "washout", "capsule", "growth", "af_malignant", "af_benign")}
    base.update({k: Feature(state=v, evidence=f"{k} words" if v != "not_documented" else "") for k, v in states.items()})
    return Extraction(size_mm=states.pop("size", 18) if "size" in states else 18, size_evidence="18 mm", **base)


def test_consensus_unanimous_keeps_state():
    merged, conf = consensus.merge([_ex(washout="present")] * 3)
    assert merged.washout.state == "present" and conf["washout"]["agreement"] == 1.0
    assert conf["washout"]["source"] is None


def test_consensus_disagreement_becomes_extractor_uncertainty():
    merged, conf = consensus.merge([_ex(washout="present"), _ex(washout="absent"), _ex(washout="present")])
    assert merged.washout.state == "uncertain" and conf["washout"]["source"] == "extractor"


def test_consensus_hedge_is_report_uncertainty():
    merged, conf = consensus.merge([_ex(washout="uncertain")] * 3)
    assert merged.washout.state == "uncertain" and conf["washout"]["source"] == "report"


def test_consensus_size_spread():
    a, b = _ex(), _ex()
    b.size_mm = 21
    merged, conf = consensus.merge([a, a, b])
    assert merged.size_mm == 18 and conf["size"]["spread_mm"] == 3


def test_grounding():
    text = "Segment VIII: small observation with arterial phase hyperenhancement and washout."
    assert is_grounded("arterial phase hyperenhancement", text)
    assert is_grounded("observation with washout", text)
    assert not is_grounded("enhancing capsule on delayed phase", text)
    ex = _ex(capsule="present")
    assert grounding_errors(ex, "nothing relevant here")


def test_scope_guard():
    assert defer_reasons("32 mm mass with rim arterial phase hyperenhancement")
    assert not defer_reasons("18 mm observation with nonrim arterial phase hyperenhancement")
    assert not defer_reasons("No tumor in vein. 20 mm observation.")


def test_scope_guard_rim_synonyms():
    lrm = "Rim APHE suggests LR-M (non-HCC malignancy)"
    assert defer_reasons("The observation in segment 8 shows ring enhancement on arterial phase.") == [lrm]
    assert defer_reasons("30 mm mass with rim enhancement and progressive fill-in.") == [lrm]
    assert defer_reasons("Peripheral rim of enhancement around a 25 mm mass.") == [lrm]
    assert not defer_reasons("18 mm observation with nonrim enhancement and washout.")
    assert not defer_reasons("18 mm observation with non-rim enhancement and washout.")
    assert not defer_reasons("22 mm observation with nonperipheral washout and an enhancing capsule.")
