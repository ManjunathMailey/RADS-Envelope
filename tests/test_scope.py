"""Scope revision scope.2: tumour thrombus (LR-TIV), treatment terms (LR-TR), ultrasound-only assessments."""
import csv
from pathlib import Path

import pytest

from radsenvelope.engine.ruleset import get_ruleset
from radsenvelope.evaluation.real_cases import load
from radsenvelope.extraction import scope
from radsenvelope.extraction.scope import defer_reasons

ROOT = Path(__file__).resolve().parents[1]
TIV, TR = "Tumour in vein (LR-TIV)", "Treated observation needs the LR-TR algorithm"
US = "Ultrasound-only assessment: LI-RADS CT/MRI does not apply (use US or CEUS LI-RADS)"


@pytest.mark.parametrize("text,reason", [
    ("40 mm mass with tumour thrombus in the portal vein.", TIV),
    ("Tumor thrombus extends into the main portal vein.", TIV),
    ("There is enhancing soft tissue in the right portal vein.", TIV),
    ("Enhancing soft-tissue in vein adjacent to the mass.", TIV),
    ("Portal vein thrombus with arterial enhancement.", TIV),
    ("An enhancing thrombus fills the left portal vein.", TIV),
    ("25 mm lesion after radiofrequency ablation.", TR),
    ("Segment VI observation, status post RFA.", TR),
    ("Microwave ablation zone in segment VII.", TR),
    ("Lesion after MWA, 20 mm.", TR),
    ("Treated with TARE in 2024.", TR),
    ("Post Y-90 radioembolization changes.", TR),
    ("Radioembolisation was performed.", TR),
    ("Observation previously treated with SBRT.", TR),
    ("Post-ablation cavity measuring 30 mm.", TR),
    ("The treated lesion measures 18 mm.", TR),
    ("A treated observation in segment II.", TR),
    ("On ultrasound, a 20 mm hypoechoic nodule in segment VI.", US),
    ("CEUS shows a 25 mm nodule.", US),
])
def test_new_scope_terms_defer(text, reason):
    assert reason in defer_reasons(text), text


@pytest.mark.parametrize("text", [
    "Untreated 25 mm observation with arterial phase hyperenhancement.",
    "No tumour thrombus. 22 mm observation with arterial phase hyperenhancement.",
    "Bland portal vein thrombus, non-enhancing.",
    "Dynamic CT scan findings were concordant with ultrasound. The lesion displayed arterial phase enhancement.",
    "MRI: 30 mm observation with washout on the portal venous phase; the ultrasound was inconclusive.",
    "Segment VI: 18 mm observation with nonrim arterial phase hyperenhancement. No washout.",
])
def test_not_deferred(text):
    assert defer_reasons(text) == [], text


def test_ruleset_revision_and_core_unchanged():
    rs = get_ruleset()
    assert rs.revision == "scope.2" and rs.raw["version"] == "2018"
    assert rs.raw["core_table"]["nonrim_aphe"][">=20"] == ["LR-4", "LR-5", "LR-5"]
    assert rs.raw["tie_break"] == {"uncertain_feature": "absent"}


def test_only_epmc008_changes_among_dev_cases(monkeypatch):
    """Every accepted development case that was not deferred before stays not deferred, except the
    tumour-thrombus case EPMC008 that motivated the revision. Test cases are not inspected."""
    split = {r["id"]: r["split"] for r in csv.DictReader(open(ROOT / "data" / "real" / "split.csv", encoding="utf-8"))}
    dev = [r for r in load() if split.get(r["id"]) == "dev"]
    now = {r["id"]: bool(defer_reasons(r["findings_text"])) for r in dev}
    rs = get_ruleset()
    monkeypatch.setattr(type(rs), "defer_patterns", lambda self: [])
    monkeypatch.setattr(type(rs), "defer_conditions", lambda self: [])
    before = {r["id"]: bool(scope.defer_reasons(r["findings_text"])) for r in dev}
    changed = sorted(i for i in now if now[i] != before[i])
    assert changed == ["EPMC008"]
