"""WAW-TACE analysis: size-label consistency rule, cut-off proximity, variability summary, xlsx reader."""
import importlib.util
import zipfile
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "data_tools"
spec = importlib.util.spec_from_file_location("wawtace_analysis", TOOLS / "wawtace_analysis.py")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def test_lr5_below_10mm_is_impossible_from_size_alone():
    assert "LR-5" not in w.reachable(9.0, 0.0)          # APHE < 10 mm caps at LR-4; ancillary cannot reach LR-5
    assert "LR-5" in w.reachable(9.0, 2.0)              # but reachable within the measurement tolerance
    assert "LR-5" in w.reachable(10.0, 0.0)
    for size in (5.0, 15.0, 40.0):
        env = w.reachable(size, 0.0)
        assert "LR-3" in env and "LR-4" in env          # LR-3 and LR-4 are reachable at every size


def test_consistency_flags_only_impossible_labels():
    les = [{"patient": "1", "lesion": 1, "diameter_mm": 9.0, "label": "LR-5"},
           {"patient": "2", "lesion": 1, "diameter_mm": 25.0, "label": "LR-5"},
           {"patient": "3", "lesion": 1, "diameter_mm": 8.0, "label": "LR-3"},
           {"patient": "4", "lesion": 1, "diameter_mm": 60.0, "label": "LR-M"}]
    exact = w.consistency(les, 0.0)
    assert exact["flagged"] == 1 and exact["flagged_cases"][0]["patient"] == "1"
    assert exact["assessable_lesions"] == 3 and exact["lr_m_not_assessed"] == 1
    assert w.consistency(les, 2.0)["flagged"] == 0


def test_cutoff_proximity_and_labels():
    les = [{"diameter_mm": d, "label": lab} for d, lab in [(9.0, "LR-4"), (19.0, "LR-5"), (35.0, "LR-5"), (13.0, "LR-3")]]
    p = w.cutoff_proximity(les, {"m2": 2.0})["m2"]
    assert p["near"] == 2 and p["by_label"]["LR-5"] == {"near": 1, "lesions": 2, "share": 0.5}
    assert w.label("5.0") == "LR-5" and w.label("M") == "LR-M" and w.label("") is None


def test_variability_bland_altman():
    rows = [{"dataset": "WAW-TACE", "patient_id": p, "measured_size_mm": str(m), "reference_size_mm": str(r)}
            for p, m, r in [("1", 22, 20), ("1", 10, 20), ("2", 30, 30), ("3", 41, 45)]]
    v = w.variability(rows)
    assert v["patients"] == 3 and v["median_abs_diff_mm"] == 2.0       # per patient: largest mask vs clinical
    assert v["bland_altman"]["bias_mm"] == pytest.approx((2 + 0 - 4) / 3, abs=0.01)


def test_report_builder_sections_and_labels():
    spec_b = importlib.util.spec_from_file_location("build_evaluation_report", TOOLS / "build_evaluation_report.py")
    b = importlib.util.module_from_spec(spec_b)
    spec_b.loader.exec_module(b)
    text = b.build()
    for heading in ("## 1. Protocol", "## 2. Development set", "## 3. Test set", "## 4. Size-tolerance sensitivity",
                    "## 5. Repeatability", "## 6. Inter-annotator agreement", "## 8. Real-patient label analysis",
                    "## 9. Robustness test (rule-generated gold)", "## 10. Limitations"):
        assert heading in text
    robustness = text.split("## 9. Robustness test")[1].split("## 10.")[0]
    assert "Not an accuracy measure" in robustness and "Accuracy [95% CI]" not in robustness
    assert "not yet collected (single reviewer)" in text.lower()
    assert "phase codes are unverified" in text


def test_xlsx_reader(tmp_path):
    p = tmp_path / "t.xlsx"
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2"><v>446</v></c><c r="B2" t="s"><v>2</v></c></row></sheetData></worksheet>')
    shared = ('<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>PATPRI</t></si>'
              '<si><t>lesion1_LIRADS</t></si><si><t>M</t></si></sst>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", shared)
    assert w.read_xlsx(p) == [{"PATPRI": "446", "lesion1_LIRADS": "M"}]
