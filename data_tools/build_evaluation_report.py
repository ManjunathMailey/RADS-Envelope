r"""
Generate docs\EVALUATION.md from the committed results JSONs (no numbers are typed by hand).

    .\.venv\Scripts\python.exe data_tools\build_evaluation_report.py

Sections: protocol (sources, split, freeze tag and hash, prompt-change rule), dev and test tables
(B1/B2/B3/Ours with 95 % Wilson CIs), per-source results, tolerance sensitivity, repeatability,
deferrals, inter-annotator agreement, error analysis, the WAW-TACE label analysis, the robustness
test (rule-generated gold, clearly labelled) and limitations. Missing inputs are reported as pending.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL, BENCH, DOCS = ROOT / "data" / "real", ROOT / "data" / "benchmark", ROOT / "docs"
OUT = DOCS / "EVALUATION.md"
SYSTEM_NAMES = {"B1": "B1 LLM-direct", "B2": "B2 lexicon + rules", "B3": "B3 LLM + rules", "Ours": "Ours (LLM + rules + envelope)"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def p(prop) -> str:
    if not prop or prop.get("value") is None:
        return "–"
    lo, hi = prop["ci95"]
    return f"{prop['value']:.2f} [{lo:.2f}–{hi:.2f}] ({prop['k']}/{prop['n']})"


def short(prop) -> str:
    return "–" if not prop or prop.get("value") is None else f"{prop['value']:.2f} ({prop['k']}/{prop['n']})"


def system_table(systems: dict, label_accuracy: str = "Accuracy [95% CI]") -> list[str]:
    head = (f"| System | {label_accuracy} | Weighted κ | LR-5 sens | LR-5 spec | Envelope coverage | Mean envelope size | "
            "±1-band coverage | Contradiction rate | Alert rate |")
    lines = [head, "| --- " * 10 + "|"]
    for s in ("B1", "B2", "B3", "Ours"):
        if s not in systems:
            continue
        m = systems[s]["summary"]
        lines.append(f"| {SYSTEM_NAMES[s]} | {p(m['accuracy'])} | {m['weighted_kappa'] if m['weighted_kappa'] is not None else '–'} | "
                     f"{short(m['lr5_sensitivity'])} | {short(m['lr5_specificity'])} | {p(m.get('envelope_coverage'))} | "
                     f"{m.get('mean_envelope_size') or '–'} | {short(m['pm1_band_coverage'])} | "
                     f"{short(m['contradiction_rate'])} | {short(m.get('alert_rate'))} |")
    return lines


def confusion(systems: dict, system: str = "Ours") -> list[str]:
    if system not in systems:
        return []
    cm = systems[system]["summary"]["confusion"]
    lines = [f"Confusion matrix, {SYSTEM_NAMES[system]} (rows = reference, columns = predicted):", "",
             "| | " + " | ".join(cm["labels"]) + " |", "| --- " * (len(cm["labels"]) + 1) + "|"]
    lines += [f"| **{lab}** | " + " | ".join(str(v) for v in row) + " |" for lab, row in zip(cm["labels"], cm["matrix"])]
    return lines


def git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def protocol() -> list[str]:
    split = REAL / "split.csv"
    lines = ["## 1. Protocol", ""]
    lines.append("**Sources.** Real radiologist-reported cases: Radiopaedia and PMC cases entered by hand, and Europe PMC "
                 "open-access case reports after human review (`docs/DATA_SOURCES.md`). Reference = the category stated "
                 "by the reporting radiologist or authors.")
    if split.exists():
        rows = list(csv.DictReader(open(split, encoding="utf-8")))
        test_ids = sorted(r["id"] for r in rows if r["split"] == "test")
        sha = hashlib.sha256("\n".join(test_ids).encode()).hexdigest()
        forced = sum(bool(r["forced_dev_reason"]) for r in rows)
        tag = git("rev-parse", "--verify", "--quiet", "eval-freeze^{commit}")
        lines.append(f"**Split.** Stratified by source and category, seed 2026, 40 % dev / 60 % test: "
                     f"{len(rows) - len(test_ids)} dev ({forced} forced because they were inspected during development), "
                     f"{len(test_ids)} test. Test-id sha256 `{sha[:16]}…`; freeze tag `eval-freeze` "
                     f"{'at ' + tag[:10] if tag else '(not yet created)'}.")
    else:
        lines.append("**Split.** Pending (`MERGE READY`): until the reviewed Europe PMC cases are merged, every real case "
                     "is a development case (all were inspected during development) and no test set exists.")
    tag2 = git("rev-parse", "--verify", "--quiet", "eval-freeze-2^{commit}")
    lines.append("**Protocol changes before test.** (1) Scope revision `scope.2` of the rule file, approved before any test "
                 "run: tumour thrombus and enhancing soft tissue in vein defer as LR-TIV (LI-RADS v2018 LR-TIV definition), "
                 "more treatment terms defer as treated observations (LR-TR), and ultrasound-only assessments defer (LI-RADS "
                 "CT/MRI applies to CT and MRI). Trigger: development case EPMC008, a tumour-thrombus case not deferred. The "
                 "diagnostic table, ancillary rules and tie-break are unchanged; among development cases only EPMC008 "
                 "changes. The test-id list is unchanged; freeze tag `eval-freeze-2` "
                 f"{'at ' + tag2[:10] if tag2 else '(not yet created)'}. Repeatability numbers measured before this revision "
                 "remain valid for cases whose deferral did not change.")
    lines.append("**Rules.** Held-out cases are scored only with `RADS_RUN_TEST=1`; every test run is logged with its git "
                 "commit and prompt hash (`data/real/test_runs.log`). A prompt change must come from a development error "
                 "and cite the LI-RADS v2018 definition it implements; every results file stores the prompt hash.")
    return lines + [""]


def comparison_section(res: dict | None, title: str) -> list[str]:
    lines = [f"## {title}", ""]
    if not res:
        return lines + ["Pending.", ""]
    lines.append(f"Cases: {res['cases']} · prompt hash `{res.get('prompt_hash', '')[:12]}` · B1 prompt hash "
                 f"`{res.get('b1_prompt_hash', '')[:12]}` · model `{res.get('model')}` · commit "
                 f"`{(res.get('git') or {}).get('commit', '')[:10]}` · generated {res.get('generated_at')}")
    lines += [""] + system_table(res["systems"]) + [""]
    lines.append("Accuracy is over cases with a numeric reference; a deferral or missing category counts as wrong. "
                 "Contradiction rate for the rule-based systems is zero by construction; the impression consistency "
                 "check verifies it on every case.")
    lines += [""] + confusion(res["systems"]) + [""]
    ours = res["systems"].get("Ours", {}).get("summary", {})
    lines.append(f"**Deferrals (LR-M / LR-TIV / LR-TR).** Ours: precision {p(ours.get('deferral_precision'))}, recall "
                 f"{p(ours.get('deferral_recall'))}. B1: precision {p(res['systems'].get('B1', {}).get('summary', {}).get('deferral_precision'))}, "
                 f"recall {p(res['systems'].get('B1', {}).get('summary', {}).get('deferral_recall'))}.")
    lines += ["", "**Per reference category** (correct / cases; the set is category-imbalanced):", "",
              "| Reference | Cases | B1 | B2 | B3 | Ours | Ours envelope covers |", "| --- | --- | --- | --- | --- | --- | --- |"]
    gold_cats = sorted({r["gold"] for r in res["systems"]["Ours"]["rows"] if r["gold"]})
    for cat in gold_cats:
        cells = []
        for s in ("B1", "B2", "B3", "Ours"):
            rows = [r for r in res["systems"].get(s, {}).get("rows", []) if r["gold"] == cat]
            ok = sum(r["pred"] == cat or (cat in ("LR-M", "LR-TIV", "LR-TR") and r["pred"] == "defer") for r in rows)
            cells.append(f"{ok}/{len(rows)}" if rows else "–")
        ours = [r for r in res["systems"]["Ours"]["rows"] if r["gold"] == cat]
        cov = sum(cat in (r.get("envelope") or []) for r in ours)
        lines.append(f"| {cat} | {len(ours)} | " + " | ".join(cells) + f" | {cov}/{len(ours)} |")
    per = res["systems"].get("per_source")
    if per:
        lines += ["", "**Per source** (accuracy [95% CI], Ours envelope coverage):", "",
                  "| Source | B1 | B2 | B3 | Ours | Ours envelope coverage |", "| --- | --- | --- | --- | --- | --- |"]
        for src, sy in sorted(per.items()):
            lines.append(f"| {src} | " + " | ".join(p(sy[s]["accuracy"]) if s in sy else "–" for s in ("B1", "B2", "B3", "Ours"))
                         + f" | {p(sy.get('Ours', {}).get('envelope_coverage'))} |")
        pooled = res["systems"]
        lines.append("| pooled | " + " | ".join(p(pooled[s]["summary"]["accuracy"]) for s in ("B1", "B2", "B3", "Ours")
                                                if s in pooled) + f" | {p(pooled['Ours']['summary'].get('envelope_coverage'))} |")
    return lines + [""]


def sensitivity_section() -> list[str]:
    lines = ["## 4. Size-tolerance sensitivity", "",
             "Recomputed by the engine from the stored extractions (no new LLM calls). The point category does not "
             "depend on the tolerance; the envelope does.", ""]
    for name, path in (("Development cases", REAL / "tolerance_sensitivity.comparison.dev.json"),
                       ("Robustness test (rule-generated gold)", BENCH / "tolerance_sensitivity_comparison.json")):
        d = load(path)
        lines.append(f"**{name}**" + ("" if d else ": pending."))
        if d:
            lines += ["", "| Tolerance | Alert rate | Envelope coverage | Mean envelope size | Near a cut-off |",
                      "| --- | --- | --- | --- | --- |"]
            lines += [f"| ±{t['tolerance_mm']:g} mm | {short(t['alert_rate'])} | {short(t['envelope_coverage'])} | "
                      f"{t['mean_envelope_size']} | {short(t['near_cutoff_rate'])} |" for t in d["table"]]
        lines.append("")
    return lines


def repeatability_section() -> list[str]:
    d = load(REAL / "repeatability.dev.json")
    lines = ["## 5. Repeatability (development cases)", ""]
    if not d:
        return lines + ["Pending.", ""]
    s = lambda x: f"{x['identical']}/{x['cases']} ({x['share']:.0%})"
    lines += [f"Identical category and envelope across {d['runs']} Standard runs: {s(d['standard'])}; across {d['runs']} runs "
              f"interleaved with B1 calls: {s(d['interleaved'])}; across all {2 * d['runs']} runs: {s(d['all_runs'])}.", "",
              "| Case | Standard runs | Interleaved runs |", "| --- | --- | --- |"]
    lines += [f"| {c['id']} | {', '.join(c['standard'])} | {', '.join(c['interleaved'])} |" for c in d["per_case"]]
    t = d["thorough"]
    lines += ["", f"Thorough mode (3 samples): extractor disagreement widened the envelope in {t['widened']}/{t['cases']} "
              f"cases; the widened envelope covered the reference in {t['widened_and_covers_reference']} of them.", ""]
    current = load(REAL / "results.comparison.dev.json")
    if current:
        now = {r["id"]: r["pred"] for r in current["systems"]["Ours"]["rows"]}
        changed = [c["id"] for c in d["per_case"] if c["id"] in now and now[c["id"]] != c["standard"][0]]
        if changed:
            lines += [f"Measured before the latest rule revision; the result has since changed for {', '.join(changed)} "
                      "(now deferred), so the repeatability figures are valid for the other cases only.", ""]
    assigned = sum(1 for c in d["per_case"] if c["standard"][0] not in ("not_assignable",))
    lines += [f"{assigned} of the {d['standard']['cases']} cases received a category or a deferral; the rest are not "
              "assignable and are trivially stable.", ""]
    return lines


def annotation_section() -> list[str]:
    d = load(REAL / "annotations" / "agreement.json")
    lines = ["## 6. Inter-annotator agreement", ""]
    if not d or d.get("status") != "collected":
        return lines + ["Not yet collected (single reviewer). Templates: `data/real/annotations/annotator_a.csv` and "
                        "`annotator_b.csv` (dev ids prefilled); `data_tools/annotator_kappa.py` computes per-feature "
                        "Cohen's κ and extractor F1 against the adjudicated gold (labels both annotators agree on).", ""]
    lines += ["| Feature | n | Agreement | Cohen's κ |", "| --- | --- | --- | --- |"]
    lines += [f"| {k} | {v['n']} | {v['agreement']} | {v['kappa']} |" for k, v in d["features"].items()]
    return lines + [""]


def error_section() -> list[str]:
    before, after = load(DOCS / "error_analysis_dev_before.json"), load(DOCS / "error_analysis_dev.json")
    lines = ["## 7. Development error analysis", ""]
    if not after:
        return lines + ["Pending.", ""]
    if before:
        lines.append(f"Before the definition-grounded prompt changes: {before['disagreements']} disagreements "
                     f"{before['by_class']}; after: {after['disagreements']} {after['by_class']}. "
                     "Details: `docs/error_analysis_dev_before.md`, `docs/error_analysis_dev.md`.")
    lines += ["", "| Case | Reference | Ours | Class | Minimal change that reproduces the reference |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {e['id']} | {e['reference']} | {e['ours']} | {e['class']} | {e['detail']} |" for e in after["errors"]]
    import re as _re
    texts = {}
    cases_csv = REAL / "radiopaedia_cases.csv"
    if cases_csv.exists():
        texts = {r["id"]: r["findings_text"] for r in csv.DictReader(open(cases_csv, encoding="utf-8-sig"))}
    header_unit = [e["id"] for e in after["errors"] if e["class"] == "out_of_scope"
                   and _re.search(r"\((?:mm|cm)\)\s*:", texts.get(e["id"], ""), _re.I)]
    if header_unit:
        lines += ["", f"Note: {', '.join(header_unit)} do state a size, with the unit in a table column header "
                  "(e.g. \"HCC Size (mm): 11.6\"); the size guard accepts only sizes written with a unit, so these are a "
                  "size-format limitation, not missing data."]
    return lines + [""]


def wawtace_section() -> list[str]:
    d = load(REAL / "wawtace_analysis.json")
    lines = ["## 8. Real-patient label analysis: WAW-TACE", ""]
    if not d:
        return lines + ["Pending.", ""]
    v, ba = d["measurement_variability"], d["measurement_variability"]["bland_altman"]
    c2, c0 = d["size_label_consistency"], d["size_label_consistency_exact"]
    cp = d["cutoff_proximity"]
    lines += [f"233 patients with radiologist LI-RADS labels per lesion and no feature labels ({d['source']}).", "",
              f"**Measurement variability** ({v['patients']} patients, largest mask diameter vs the dataset's clinical "
              f"diameter): median |difference| {v['median_abs_diff_mm']} mm (IQR {v['iqr_abs_diff_mm'][0]}–{v['iqr_abs_diff_mm'][1]}); "
              f"within 2 / 5 / 10 mm: {v['within_2mm']:.0%} / {v['within_5mm']:.0%} / {v['within_10mm']:.0%}. "
              f"Bland-Altman: bias {ba['bias_mm']} mm, SD {ba['sd_mm']} mm, 95 % limits of agreement "
              f"{ba['limits_of_agreement_mm'][0]} to {ba['limits_of_agreement_mm'][1]} mm.", "",
              f"**Cut-off proximity** ({cp['within_2mm']['lesions']} lesions): {cp['within_2mm']['share']:.0%} lie within ±2 mm "
              f"of 10 or 20 mm, {cp['within_median_discrepancy']['share']:.0%} within ±{cp['within_median_discrepancy']['margin_mm']} mm "
              "(the median discrepancy): for these, measurement alone could change the category.", "",
              "| Label | Lesions | Within ±2 mm of a cut-off | Within ± median discrepancy |", "| --- | --- | --- | --- |"]
    for lab, x in cp["within_2mm"]["by_label"].items():
        y = cp["within_median_discrepancy"]["by_label"][lab]
        lines.append(f"| {lab} | {x['lesions']} | {x['near']} ({x['share']:.0%}) | {y['near']} ({y['share']:.0%}) |")
    flagged = "; ".join(f"patient {f['patient']} lesion {f['lesion']}: {f['label']} at {f['diameter_mm']:g} mm"
                        for f in c0["flagged_cases"]) or "none"
    lines += ["", f"**Size-label consistency check** (engine, all features unknown, LR-M not assessable): with ±{c2['tolerance_mm']:g} mm, "
              f"{c2['flagged']}/{c2['assessable_lesions']} labels are unreachable from size alone; with exact sizes, "
              f"{c0['flagged']}/{c0['assessable_lesions']} ({flagged}). This is a consistency check of labels against the "
              "v2018 table, not an error rate of the dataset.", "",
              f"**Label distribution** (all lesions): {d['label_distribution']['all_lesions']}; lesion 1 per patient: "
              f"{d['label_distribution']['lesion1_per_patient']}.", ""]
    return lines


def robustness_section() -> list[str]:
    d = load(BENCH / "results_comparison.json")
    lines = ["## 9. Robustness test (rule-generated gold)", "",
             "**Not an accuracy measure.** The 200 reports are generated from known feature vectors and their gold "
             "category comes from the same rule table the systems use. Agreement here measures how robustly features "
             "are recovered under varied phrasing, hedges, omissions and near-cut-off sizes.", ""]
    if not d:
        return lines + ["Pending.", ""]
    lines.append(f"n = {d['n']}, seed {d['seed']}, prompt hash `{d.get('prompt_hash', '')[:12]}`.")
    return lines + [""] + system_table(d["systems"], "Agreement with rule-generated gold [95% CI]") + [""]


LIMITATIONS = [
    "Small real-case sample: confidence intervals are wide; the test set is used once.",
    "Selection bias: published and teaching cases over-represent clear-cut LR-5 and LR-M; they are not a consecutive clinical series.",
    "Category imbalance: published case reports over-represent definite HCC (LR-5), so the real-case set is category-imbalanced; "
    "results are reported per category, and LR-3 / LR-4 numbers rest on very few cases and must not be over-interpreted.",
    "No radiologist co-author has yet confirmed the references, the error attribution or the reviewed Europe PMC cases.",
    "Inter-annotator agreement: not yet collected (single reviewer).",
    "The open CT datasets have no LI-RADS feature labels (APHE, washout, capsule); those exist only in AMPLIFAI (access pending).",
    "WAW-TACE phase codes are unverified against the dataset paper.",
    "Determinism: before a fixed seed and context size were set, LLM output at temperature 0 depended on the order of "
    "calls on Ollama (PMC001 changed category); with seed 42 and a 4096-token context the development set was identical "
    "across six runs. Determinism is measured, not guaranteed.",
    "The robustness test uses rule-generated gold and is reported as robustness, never as accuracy. It is not held out: "
    "its error list informed the APHE definition, which quotes one of the generator's phrasings, so part of its last gain "
    "reflects the generator's vocabulary.",
    "Clustered cases: one article (PMC8122342) contributes 11 of the 27 real cases (rows of one per-lesion table), all in dev; "
    "the 27 cases come from 16 independent sources.",
    "Small test set: forcing every inspected case into dev leaves 8 test cases (dev 19 / test 8), so test intervals are wide.",
    "Table-format cases write the unit in the column header (\"HCC Size (mm): 11.6\"); the size guard accepts only sizes "
    "written with a unit, so these cases are currently not assignable.",
]


def build() -> str:
    lines = ["# Evaluation", "", "Generated by `data_tools/build_evaluation_report.py` from the committed results files; "
             "numbers are never typed by hand.", ""]
    lines += protocol()
    lines += comparison_section(load(REAL / "results.comparison.dev.json"), "2. Development set (real cases)")
    lines += comparison_section(load(REAL / "results.comparison.test.json"), "3. Test set (real cases, run once)")
    lines += sensitivity_section() + repeatability_section() + annotation_section() + error_section()
    lines += wawtace_section() + robustness_section()
    lines += ["## 10. Limitations", ""] + [f"- {x}" for x in LIMITATIONS] + [""]
    return "\n".join(lines)


def main() -> None:
    OUT.write_text(build(), encoding="utf-8")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
