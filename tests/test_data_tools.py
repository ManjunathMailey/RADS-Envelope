"""Data tools: license filter, verbatim candidate extraction from JATS, merge of reviewed rows."""
import csv
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

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
    for ok in ("cc by", "CC BY-NC", "cc0", "cc by-sa", "cc by-nc-sa"):
        assert harvest.license_allowed(ok)
    for bad in ("cc by-nd", "cc by-nc-nd", "", None, "other"):        # no-derivatives or unknown: excluded
        assert not harvest.license_allowed(bad)


def test_category_sentences_skip_ultrasound():
    assert extract.category_sentences("The nodule was LR-4 on MRI.")[0][1] == ["LR-4"]
    assert extract.category_sentences("CEUS LR-5 was assigned.") == []
    assert extract.category_sentences("US LI-RADS 3 nodule.") == []
    assert extract.category_sentences("Per LI-RADS v2018 category 5 criteria.")[0][1] == ["LR-5"]
    assert extract.category_sentences("Liver Imaging Reporting and Data System (LI-RADS) score was 4.")[0][1] == ["LR-4"]
    assert extract.category_sentences("Two major features according to LI-RADS v2018 [30].") == []
    assert extract.category_sentences("Evaluated with the CT/MRI LI-RADS (Version 2018) criteria.") == []


def test_group_statistics_are_not_case_labels():
    assert extract.category_sentences("Of the 120 observations, 45 were LR-5.") == []
    assert extract.category_sentences("LR-5 had a sensitivity of 72% for HCC.") == []
    assert extract.category_sentences("The 23 mm nodule was categorized as LR-4.")[0][1] == ["LR-4"]


TABLE_JATS = """<article><body><sec><title>Results</title>
<p>Of the 3 patients, 2 were LR-5 (67%).</p>
<table-wrap><label>Table 2</label><caption><p>Per-lesion MRI features</p></caption><table>
<thead><tr><th>Patient</th><th>Size (mm)</th><th>APHE</th><th>Washout</th><th>Capsule</th><th>LI-RADS</th></tr></thead>
<tbody><tr><td>1</td><td>24</td><td>Yes</td><td>Yes</td><td>No</td><td>LR-5</td></tr>
<tr><td>2</td><td>12</td><td>Yes</td><td>No</td><td>No</td><td>3</td></tr>
<tr><td>3</td><td>18</td><td>No</td><td>No</td><td>No</td><td>n/a</td></tr></tbody></table></table-wrap>
<table-wrap><label>Table 3</label><caption><p>Counts</p></caption><table>
<thead><tr><th>Feature</th><th>LR-3</th><th>LR-4</th><th>LR-5</th></tr></thead>
<tbody><tr><td>APHE</td><td>4</td><td>9</td><td>20</td></tr></tbody></table></table-wrap>
</sec></body></article>"""


def test_per_lesion_table_rows_become_candidates():
    art = {"pmcid": "PMC3", "authors": "Lee K.", "journal": "J", "year": "2023", "license": "cc by-sa"}
    rows = extract.candidates_for(art, ET.fromstring(TABLE_JATS))
    assert [r["radiologist_category"] for r in rows] == ["LR-5", "LR-3"]   # results prose, n/a row and counts table skipped
    assert rows[0]["findings_text"] == "Patient: 1; Size (mm): 24; APHE: Yes; Washout: Yes; Capsule: No"
    assert "Table 2" in rows[0]["notes"] and "row 1" in rows[0]["notes"] and rows[1]["category_sentence"] == "LI-RADS: 3"
    assert rows[0]["license"] == "CC BY-SA" and rows[0]["modality"] == "MRI"


def test_cohort_articles_give_prose_only_from_case_sections():
    jats = """<article><body>
    <sec><title>Image analysis</title><p>On CT, a 25 mm liver observation showed arterial phase hyperenhancement and
    washout. It was categorized as LR-5 by two readers.</p></sec>
    <sec><title>Case 1</title><p>MRI showed a 22 mm liver mass in segment 6 with arterial phase hyperenhancement and
    washout. It was categorized as LR-5.</p></sec></body></article>"""
    cohort = {"pmcid": "PMC4", "authors": "A B.", "journal": "J", "year": "2024", "license": "cc by",
              "queries": ["q3_features"]}
    rows = extract.candidates_for(cohort, ET.fromstring(jats))
    assert [r["notes"].split("section: ")[1] for r in rows] == ["Case 1"]
    case = dict(cohort, queries=["q1_case_reports", "q3_features"])
    assert len(extract.candidates_for(case, ET.fromstring(jats))) == 2


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


def test_extractor_refuses_to_overwrite_reviewed_file(tmp_path, monkeypatch):
    reviewed = tmp_path / "candidates.csv"
    with open(reviewed, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=extract.COLUMNS)
        w.writeheader()
        w.writerow({**{c: "" for c in extract.COLUMNS}, "id": "EPMC-CAND-0001", "review_status": "accept"})
    before = reviewed.read_bytes()
    monkeypatch.setattr(extract, "OUT", reviewed)
    with pytest.raises(SystemExit, match="review decisions"):
        extract.main([])
    assert reviewed.read_bytes() == before                      # untouched
    assert extract.has_review(reviewed)
    unreviewed = tmp_path / "fresh.csv"
    unreviewed.write_text(",".join(extract.COLUMNS) + "\nX" + "," * (len(extract.COLUMNS) - 1) + "\n", encoding="utf-8")
    assert not extract.has_review(unreviewed) and not extract.has_review(tmp_path / "missing.csv")


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
