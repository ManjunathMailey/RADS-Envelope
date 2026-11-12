r"""
Error analysis of development-set disagreements.

    .\.venv\Scripts\python.exe data_tools\error_analysis.py [--results data\real\results.comparison.dev.json]
                                                           [--out docs\error_analysis_dev.md] [--title "..."]

Reads a dev comparison result (never a test result: the script refuses files whose split is not
"dev") and classifies every case where Ours disagrees with the radiologist's category:

  scope_error          deferral wrong: an LR-M/LR-TIV/LR-TR reference not deferred, or a numeric
                       reference deferred
  size_error           no size used although the text writes one, or only a different size bucket
                       reproduces the reference
  extraction_error     changing one (or two) extracted features reproduces the reference; the
                       features, the extracted state and the model's evidence are listed
  out_of_scope         the findings text gives no size, so no category can be assigned
  reference_ambiguous  no single or double feature change and no size change reproduces the reference:
                       the reference conflicts with the findings as written
  other                anything else

The attribution is the minimal change that the deterministic engine needs to reach the reference;
it is a candidate explanation for a human to confirm, not a ground-truth label.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radsenvelope.engine.ruleset import FEATURES, get_ruleset  # noqa: E402
from radsenvelope.extraction.sizes import parse_sizes  # noqa: E402
from radsenvelope.pipeline import run_observation  # noqa: E402

DEFER = {"LR-M", "LR-TIV", "LR-TR"}
ALT = {"present": ["absent"], "absent": ["present"], "uncertain": ["present", "absent"],
       "not_documented": ["present", "absent"]}


def _cat(features: dict, size, tol: float = 0.0) -> str | None:
    return run_observation("x", features, size, tol, True, []).get("acr_category")


def classify(row: dict, text: str) -> dict:
    gold, pred, feats, size = row["gold"], row["pred"], row.get("features") or {}, row.get("size_mm")
    base = {"id": row["id"], "reference": gold, "ours": pred, "envelope": row.get("envelope")}
    if gold in DEFER:
        return {**base, "class": "scope_error", "detail": f"reference {gold} not deferred (ours {pred})"}
    if pred == "defer":
        return {**base, "class": "scope_error", "detail": "deferred although the reference is "
                f"{gold}; reasons: {'; '.join(row.get('defer_reasons') or [])}"}
    if pred == "not_assignable" or size is None:
        written = [s["text"] for s in parse_sizes(text)]
        if written:
            return {**base, "class": "size_error", "detail": f"no size used although the text writes {written}"}
        return {**base, "class": "out_of_scope", "detail": "the findings text states no size"}
    single = []
    for k in FEATURES:
        for alt in ALT.get(feats.get(k, "not_documented"), []):
            if _cat({**feats, k: alt}, size) == gold:
                single.append({"feature": k, "extracted": feats.get(k, "not_documented"), "needed": alt,
                               "evidence": (row.get("evidence") or {}).get(k, "")})
    if single:
        return {**base, "class": "extraction_error", "features": single,
                "detail": "; ".join(f"{s['feature']}: {s['extracted']} -> {s['needed']}" for s in single)}
    rs = get_ruleset()
    probes = [c - 0.5 for c in rs.cutoffs] + [c + 0.5 for c in rs.cutoffs]
    if any(_cat(feats, s) == gold for s in probes):
        return {**base, "class": "size_error",
                "detail": f"only a different size bucket reproduces {gold} (size used {size} mm, "
                          f"evidence '{row.get('size_evidence', '')}')"}
    for k1, k2 in itertools.combinations(FEATURES, 2):
        for a1 in ALT.get(feats.get(k1, "not_documented"), []):
            for a2 in ALT.get(feats.get(k2, "not_documented"), []):
                if _cat({**feats, k1: a1, k2: a2}, size) == gold:
                    return {**base, "class": "extraction_error",
                            "features": [{"feature": k1, "extracted": feats.get(k1), "needed": a1,
                                          "evidence": (row.get("evidence") or {}).get(k1, "")},
                                         {"feature": k2, "extracted": feats.get(k2), "needed": a2,
                                          "evidence": (row.get("evidence") or {}).get(k2, "")}],
                            "detail": f"two features: {k1} {feats.get(k1)} -> {a1}, {k2} {feats.get(k2)} -> {a2}"}
    if gold is None or not gold.startswith("LR-"):
        return {**base, "class": "other", "detail": f"reference '{gold}' not usable"}
    return {**base, "class": "reference_ambiguous",
            "detail": "no single or double feature change and no size change reproduces the reference"}


def analyse(results: dict, texts: dict[str, str]) -> dict:
    if results.get("split") not in ("dev", None):
        raise SystemExit(f"Refusing: error analysis is for the development split only (got '{results.get('split')}').")
    rows = results["systems"]["Ours"]["rows"]
    errors = [classify(r, texts.get(r["id"], "")) for r in rows if r["pred"] != r["gold"]
              and not (r["gold"] in DEFER and r["pred"] == "defer")]
    counts: dict[str, int] = {}
    for e in errors:
        counts[e["class"]] = counts.get(e["class"], 0) + 1
    return {"cases": len(rows), "disagreements": len(errors), "by_class": counts, "errors": errors,
            "prompt_hash": results.get("prompt_hash"), "generated_from": results.get("generated_at")}


def to_markdown(a: dict, title: str) -> str:
    lines = [f"# {title}", "",
             f"Development cases: {a['cases']}. Disagreements with the radiologist's category: {a['disagreements']}. "
             f"Prompt hash: `{(a.get('prompt_hash') or '')[:12]}`.", "",
             "Each disagreement is attributed to the minimal change the deterministic engine needs to reproduce "
             "the reference (`data_tools/error_analysis.py`). This is a candidate explanation to be confirmed by a "
             "radiologist, not a ground-truth label. Test cases are never analysed.", "",
             "| Class | Count |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in sorted(a["by_class"].items())] or ["| (none) | 0 |"]
    lines += ["", "| Case | Reference | Ours | Envelope | Class | Detail | Model evidence |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for e in a["errors"]:
        ev = "; ".join(f"{f['feature']}: \"{f['evidence']}\"" for f in e.get("features", []) if f.get("evidence"))
        lines.append(f"| {e['id']} | {e['reference']} | {e['ours']} | {'/'.join(e['envelope'] or []) or '-'} | "
                     f"{e['class']} | {e['detail']} | {ev or '-'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    from radsenvelope.evaluation.real_cases import load
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, default=ROOT / "data" / "real" / "results.comparison.dev.json")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "error_analysis_dev.md")
    ap.add_argument("--title", default="Error analysis: development set")
    a = ap.parse_args()
    results = json.loads(a.results.read_text(encoding="utf-8"))
    texts = {r["id"]: r["findings_text"] for r in load()}
    res = analyse(results, texts)
    a.out.write_text(to_markdown(res, a.title), encoding="utf-8")
    a.out.with_suffix(".json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("cases", "disagreements", "by_class")}, indent=1))
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
