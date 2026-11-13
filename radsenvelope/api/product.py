"""
Product features built on top of the engine's output (no rule, engine or extraction change):

* report_check    stated category in the report vs the rule-based category, per observation
* impression_diff word-level diff of the generated impression against the stated impression
* addendum        one deterministic sentence per answered feature (templates, no language model)
* completeness    documented required items / total, with the missing items named
* audit_csv       batch export (id, stated, computed, envelope, management, decision_critical,
                  completeness, missing)
"""
from __future__ import annotations

import csv
import difflib
import io
import re

from radsenvelope.engine.ruleset import FEATURE_LABELS, get_ruleset

# ---------------- report check ----------------
CHECK_LABELS = {
    "consistent": "Consistent",
    "contradicts": "Contradicts the rules: stated category outside the envelope",
    "inside_envelope": "Stated category inside the envelope, but not the ACR tie-break category",
    "not_assessable": "Not assessable: no category assigned automatically",
}
DEFERRED_CATEGORIES = ("LR-M", "LR-TIV", "LR-TR")


def report_check(stated: str | None, result: dict) -> dict | None:
    """Compare a stated category with the engine result for one observation (None if nothing stated)."""
    if not stated:
        return None
    computed, envelope = result.get("acr_category"), result.get("envelope") or []
    if result.get("status") != "assigned":
        status = "consistent" if (stated in DEFERRED_CATEGORIES and result.get("status") == "defer") else "not_assessable"
    elif stated == computed:
        status = "consistent"
    elif stated in envelope:
        status = "inside_envelope"
    else:
        status = "contradicts"
    return {"stated": stated, "computed": computed or result.get("status"), "envelope": envelope,
            "status": status, "label": CHECK_LABELS[status]}


def impression_diff(stated: str, generated: str) -> list[dict]:
    """Word-level diff: [{op: equal|delete|insert, text}] where delete = only in the stated impression
    and insert = only in the generated one. Uses difflib (standard library)."""
    a, b = re.findall(r"\S+", stated or ""), re.findall(r"\S+", generated or "")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": " ".join(a[i1:i2])})
            continue
        if op in ("delete", "replace"):
            out.append({"op": "delete", "text": " ".join(a[i1:i2])})
        if op in ("insert", "replace"):
            out.append({"op": "insert", "text": " ".join(b[j1:j2])})
    return out


# ---------------- addendum ----------------
ADDENDUM = {
    "aphe": {"present": "Nonrim arterial phase hyperenhancement is present.",
             "absent": "There is no nonrim arterial phase hyperenhancement."},
    "washout": {"present": "Nonperipheral washout is present on the portal venous phase.",
                "absent": "There is no nonperipheral washout."},
    "capsule": {"present": "An enhancing capsule is present.",
                "absent": "There is no enhancing capsule."},
    "growth": {"present": "Threshold growth is present compared with prior CT or MRI.",
               "absent": "There is no threshold growth compared with prior imaging."},
    "af_malignant": {"present": "Ancillary features favouring malignancy are present.",
                     "absent": "No ancillary features favouring malignancy are seen."},
    "af_benign": {"present": "Ancillary features favouring benignity are present.",
                  "absent": "No ancillary features favouring benignity are seen."},
}


def addendum(feature: str, state: str | None = None, size_mm: float | None = None, label: str | None = None) -> str:
    """One deterministic sentence for an answered decisive question."""
    if feature == "size":
        if size_mm is None:
            raise ValueError("size_mm is required for a size addendum")
        sentence = f"On re-measurement, the observation measures {size_mm:g} mm."
    else:
        try:
            sentence = ADDENDUM[feature][state]
        except KeyError:
            raise ValueError(f"no addendum template for {feature}={state}") from None
    return f"{label}: {sentence}" if label else sentence


# ---------------- completeness ----------------
REQUIRED = ("aphe", "washout", "capsule")
ITEM_LABELS = {**{k: FEATURE_LABELS[k] for k in REQUIRED}, "size": "Observation size",
               "growth": FEATURE_LABELS["growth"]}


def completeness(features: dict, size_mm, has_prior: bool = False) -> dict:
    """Documented required items / total. Required: APHE, washout, capsule, size, and threshold
    growth when a prior study exists. Hedged ("uncertain") counts as documented."""
    items = list(REQUIRED) + ["size"] + (["growth"] if has_prior else [])
    documented = [k for k in items if (size_mm is not None if k == "size"
                                       else (features or {}).get(k, "not_documented") != "not_documented")]
    missing = [k for k in items if k not in documented]
    return {"documented": len(documented), "total": len(items), "score": round(len(documented) / len(items), 3),
            "missing": missing, "missing_labels": [ITEM_LABELS[k] for k in missing]}


# ---------------- batch export ----------------
CSV_COLUMNS = ["id", "stated", "computed", "envelope", "management", "decision_critical", "completeness", "missing"]


def management_text(result: dict) -> str:
    if result.get("status") == "assigned":
        return get_ruleset().management(result["acr_category"])
    return "Radiologist review: " + "; ".join(result.get("reasons") or [result.get("status", "")])


def audit_csv(rows: list[dict]) -> str:
    """rows: /api/audit rows (need report, label, stated, computed, envelope, management, critical, completeness)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        comp = r.get("completeness") or {}
        w.writerow({"id": f"{r.get('report')}-{r.get('label')}", "stated": r.get("stated") or "",
                    "computed": r.get("computed") or r.get("status") or "", "envelope": " ".join(r.get("envelope") or []),
                    "management": r.get("management") or "", "decision_critical": bool(r.get("critical")),
                    "completeness": f"{comp.get('documented', '')}/{comp.get('total', '')}",
                    "missing": "; ".join(comp.get("missing_labels") or [])})
    return buf.getvalue()
