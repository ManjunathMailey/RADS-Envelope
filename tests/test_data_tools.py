"""Data tools: license filter, verbatim candidate extraction from JATS, merge of reviewed rows."""
import csv
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "data_tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


harvest, extract, merge = _load("harvest_europepmc"), _load("extract_candidates"), _load("merge_reviewed")

JATS = """<article><body>
<sec><title>Introduction</title><p>LI-RADS assigns LR-5 when an observation of 20 mm shows APHE on CT and washout.</p></sec>
<sec><title>Case presentation</title>
<p>Contrast-enhanced CT showed a 25 mm mass in segment VII of the liver with nonrim arterial phase
hyperenhancement (<xref ref-type="fig" rid="f1">Fig. 1A</xref>) and washout on the portal venous phase [<xref ref-type="bibr" rid="b3">3</xref>].
An enhancing capsule was seen (Figure 2B). The observation was categorized as LI-RADS 5.</p>
<p>Ultrasound showed a hypoechoic nodule, CEUS LR-4.</p>
</sec>
<sec><title>Discussion</title><p>On MRI, LR-M is suggested by rim APHE in a liver mass.</p></sec>
</body></article>"""


def test_license_filter():
    assert harvest.license_allowed("cc by") and harvest.license_allowed("CC BY-NC") and harvest.license_allowed("cc0")
    for bad in ("cc by-sa", "cc by-nc-nd", "cc by-nc-sa", "", None):
        assert not harvest.license_allowed(bad)


def test_category_sentences_skip_ultrasound():
    assert extract.category_sentences("The nodule was LR-4 on MRI.")[0][1] == ["LR-4"]
    assert extract.category_sentences("CEUS LR-5 was assigned.") == []
    assert extract.category_sentences("US LI-RADS 3 nodule.") == []
    assert extract.category_sentences("Per LI-RADS v2018 category 5 criteria.")[0][1] == ["LR-5"]
    assert extract.category_sentences("Liver Imaging Reporting and Data System (LI-RADS) score was 4.")[0][1] == ["LR-4"]
    assert extract.category_sentences("Two major features according to LI-RADS v2018 [30].") == []
    assert extract.category_sentences("Evaluated with the CT/MRI LI-RADS (Version 2018) criteria.") == []


def test_category_sentence_mentioning_ultrasound_is_removed_but_not_used_as_label():
    jats = """<article><body><sec><title>Case</title>
    <p>CT showed a 22 mm liver mass in segment 6 with arterial phase hyperenhancement and washout.
    Knowing where the lesion was on CEUS, it was deemed a LI-RADS 4 lesion on CT. It was finally called LR-5 on MRI.</p>
    </sec></body></article>"""
    art = {"pmcid": "PMC2", "authors": "Doe J.", "journal": "J", "year": "2024", "license": "cc by"}
    r = extract.candidates_for(art, ET.fromstring(jats))[0]
    assert r["radiologist_category"] == "LR-5" and "LI-RADS" not in r["findings_text"] and "CEUS" not in r["findings_text"]
    assert r["findings_text"].startswith("CT showed a 22 mm liver mass")


def test_candidate_is_verbatim_without_figures_or_category():
    art = {"pmcid": "PMC1", "authors": "Doe J, Roe A.", "journal": "Case Rep", "year": "2025", "license": "cc by"}
    rows = extract.candidates_for(art, ET.fromstring(JATS))
    assert len(rows) == 1                                    # introduction, ultrasound and discussion skipped
    r = rows[0]
    assert r["radiologist_category"] == "LR-5" and r["modality"] == "CT" and r["author"] == "Doe J et al. (Case Rep 2025)"
    assert r["findings_text"] == ("Contrast-enhanced CT showed a 25 mm mass in segment VII of the liver with nonrim arterial "
                                  "phase hyperenhancement and washout on the portal venous phase [3]. "
                                  "An enhancing capsule was seen.")
    assert "LI-RADS 5" in r["category_sentence"] and "LI-RADS" not in r["findings_text"]
    assert r["review_status"] == "" and r["url"].endswith("/PMC1")


def test_merge_appends_accepted_rows_once(tmp_path):
    target, cands = tmp_path / "cases.csv", tmp_path / "cands.csv"
    cols = extract.BASE_COLUMNS
    with open(target, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerow({**{c: "" for c in cols}, "id": "EPMC004", "url": "u0", "findings_text": "old"})
    rows = [{**{c: "" for c in extract.COLUMNS}, "url": f"u{i}", "findings_text": f"text {i}", "review_status": s}
            for i, s in enumerate(["accept", "reject", "Accept", ""], 1)]
    with open(cands, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=extract.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    assert merge.merge(cands, target)["ids"] == ["EPMC005", "EPMC006"]
    again = merge.merge(cands, target)
    assert again["accepted_added"] == 0 and again["duplicates_skipped"] == 2
    with open(target, encoding="utf-8") as fh:
        assert [r["id"] for r in csv.DictReader(fh)] == ["EPMC004", "EPMC005", "EPMC006"]
