r"""
Precompute the landing page's interactive example with the real engine (nothing typed by hand).

    .\.venv\Scripts\python.exe data_tools\landing_demo.py

Writes web/static/landing_demo.json: an illustrative report (not a study case), its lexicon extraction with
evidence, the engine result as documented, and the engine result for each answer to the decisive question.
tests/test_landing.py recomputes it and fails if the file drifts from the engine.
"""
from __future__ import annotations

import json
from pathlib import Path

from radsenvelope.engine.ruleset import get_ruleset
from radsenvelope.pipeline import Settings, analyse_report, run_observation

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "static" / "landing_demo.json"
REPORT = ("Segment VII: 22 mm observation with nonrim arterial phase hyperenhancement. "
          "Possible washout on the portal venous phase. No enhancing capsule. Stable compared with the prior MRI.")
KEEP = ("acr_category", "meaning", "envelope", "decision_critical", "management")


def _slim(result: dict) -> dict:
    return {k: result.get(k) for k in KEEP}


def build() -> dict:
    rs = get_ruleset()
    out = analyse_report(REPORT, Settings(extractor="lexicon"))
    o = out["observations"][0]
    r = o["result"]
    q = r["decisive_questions"][0]
    answers = {}
    for answer, state in (("present", "present"), ("absent", "absent")):
        feats = {**o["features"], q["feature"]: state}
        answers[answer] = _slim(run_observation(o["label"], feats, o["size_mm"], o["size_tolerance_mm"], True,
                                                o["defer_reasons"]))
    evidence = {k: v.get("evidence", "") for k, v in o["extraction"].items() if isinstance(v, dict) and v.get("evidence")}
    return {"note": "Illustrative report, not a study case. Results computed by the rule engine (data_tools/landing_demo.py).",
            "report": REPORT, "label": o["label"], "size_mm": o["size_mm"], "features": o["features"],
            "evidence": evidence, "question": {"feature": q["feature"], "text": q["question"]},
            "documented": _slim(r), "answers": answers, "rules": r.get("rules"),
            "categories": [{"category": c, "meaning": rs.meaning(c), "management": rs.management(c)}
                           for c in ("LR-2", "LR-3", "LR-4", "LR-5")]}


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: data[k] for k in ("documented", "answers")}, ensure_ascii=False))
