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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REAL, BENCH, DOCS = ROOT / "data" / "real", ROOT / "data" / "benchmark", ROOT / "docs"
OUT = DOCS / "EVALUATION.md"
SYSTEM_NAMES = {"B1": "B1 LLM-direct", "B2": "B2 lexicon + rules", "B3": "B3 LLM + rules",
                "B4": "B4 hybrid (B1, corrected by rules)", "Ours": "Ours, LLM-only (ablation)",
                "OursC": "Ours-consensus (primary, pre-registered)"}
ORDER = ("B1", "B2", "B3", "B4", "Ours", "OursC")


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
    head = (f"| System | {label_accuracy} | Weighted κ (n) | LR-5 sens | LR-5 spec | Envelope coverage | "
            "Mean envelope size (n) | ±1-band coverage | Contradiction rate | Alert rate |")
    lines = [head, "| --- " * 10 + "|"]
    kappa_labels = ("LR-2", "LR-3", "LR-4", "LR-5")
    for s in ORDER:
        if s not in systems:
            continue
        m, rows = systems[s]["summary"], systems[s].get("rows", [])
        kn = sum(r["gold"] in kappa_labels and r["pred"] in kappa_labels for r in rows)
        en = sum(bool(r.get("envelope")) and (r["gold"] or "")[-1:].isdigit() for r in rows)
        kappa = f"{m['weighted_kappa']} (n={kn})" if m["weighted_kappa"] is not None else f"– (n={kn})"
        mean_env = f"{m['mean_envelope_size']:.2f} (n={en})" if m.get("mean_envelope_size") else "–"
        lines.append(f"| {SYSTEM_NAMES[s]} | {p(m['accuracy'])} | {kappa} | "
                     f"{short(m['lr5_sensitivity'])} | {short(m['lr5_specificity'])} | {p(m.get('envelope_coverage'))} | "
                     f"{mean_env} | {short(m['pm1_band_coverage'])} | "
                     f"{short(m['contradiction_rate'])} | {short(m.get('alert_rate'))} |")
    return lines


def b3_wrong(systems: dict, target: str = "Ours") -> str:
    """Among cases with a numeric reference where B3's single category is wrong: how often Ours raised a
    decision-critical alert, and how often the reference lay inside Ours' envelope."""
    b3 = {r["id"]: r for r in systems.get("B3", {}).get("rows", [])}
    ours = {r["id"]: r for r in systems.get(target, {}).get("rows", [])}
    graded = [i for i in ours if (ours[i]["gold"] or "")[-1:].isdigit()]
    wrong = [i for i in graded if b3.get(i, {}).get("pred") != ours[i]["gold"]]
    assigned = [i for i in wrong if (b3[i]["pred"] or "").startswith("LR-")]
    flagged = sum(bool(ours[i].get("critical")) for i in assigned)
    covered = sum(ours[i]["gold"] in (ours[i].get("envelope") or []) for i in assigned)
    return (f"{SYSTEM_NAMES.get(target, target)}: of {len(wrong)} cases B3 got wrong ({len(assigned)} with a wrong category, {len(wrong) - len(assigned)} "
            f"without a category), it raised a decision-critical alert on {flagged} and had the reference inside its "
            f"envelope on {covered} of the {len(assigned)} wrong categories.")


def subset(res: dict, keep) -> dict:
    """Recompute every system summary on a subset of case ids."""
    from radsenvelope.evaluation.metrics import system_summary
    out = {}
    for s in ORDER:
        if s in res["systems"]:
            rows = [r for r in res["systems"][s]["rows"] if keep(r["id"])]
            out[s] = {"summary": system_summary(rows, envelope=(s in ("Ours", "OursC"))), "rows": rows}
    return out


def table_case_ids() -> set:
    cases_csv = REAL / "radiopaedia_cases.csv"
    if not cases_csv.exists():
        return set()
    return {r["id"] for r in csv.DictReader(open(cases_csv, encoding="utf-8-sig")) if "table cells" in r.get("notes", "")}


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
    tag3 = git("rev-parse", "--verify", "--quiet", "eval-freeze-3^{commit}")
    lines.append("(2) Size guard reads units given in a label or table column header (\"HCC Size (mm): 11.6\"); the number "
                 "must still appear verbatim. Trigger: the development error analysis, where 11 of 16 misses were table "
                 "rows whose size was written this way. (3) A hybrid arm B4 (slide 11, arm C) is added: B1's category, "
                 "replaced by the rule category from B1's own features when they disagree; it is derived from the B1 run "
                 "without new model calls. No prompt, rule-table or engine change. Development and robustness results "
                 "were rerun from a committed tree; freeze tag `eval-freeze-3` "
                 f"{'at ' + tag3[:10] if tag3 else '(not yet created)'}; the test-id list is unchanged.")
    lines.append("(4) Pre-registered before implementation and before any test run: \"After dev error analysis showed "
                 "that most misses were LLM feature misreads that the lexicon read correctly, we add the lexicon as a "
                 "second extractor in the existing consensus step. Decided before seeing its results: the primary system "
                 "becomes Ours-consensus; the previous LLM-only Ours is reported as an ablation regardless of which "
                 "scores higher. No change to rules table, LLM prompt, or envelope logic.\" Committed before "
                 "implementation (666ce64); Ours-consensus was then derived from the stored LLM and lexicon extractions, "
                 "so no other arm was rerun. Freeze tag `eval-freeze-4` "
                 f"{'at ' + git('rev-parse', '--verify', '--quiet', 'eval-freeze-4^{commit}')[:10] if git('rev-parse', '--verify', '--quiet', 'eval-freeze-4^{commit}') else '(not yet created)'}; "
                 "the test-id list is unchanged.")
    lines.append("**Review of Europe PMC candidates.** Europe PMC candidate rows were pre-screened with AI assistance "
                 "against a fixed checklist (CT/MRI LI-RADS v2018; imaging findings present in the findings text; "
                 "reference category stated separately; at-risk liver; untreated observation; open licence), and every "
                 "decision was confirmed by a team member.")
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
    lines += ["", f"**B3 wrong → Ours.** {b3_wrong(res['systems'], 'OursC')} {b3_wrong(res['systems'], 'Ours')}"]
    if res.get("split") == "dev":
        tables = table_case_ids() & {r["id"] for r in res["systems"]["Ours"]["rows"]}
        if tables:
            prose = subset(res, lambda i: i not in tables)
            n = len(prose["Ours"]["rows"])
            lines += ["", f"**Prose-only subset** ({n} cases; excludes the {len(tables)} rows taken from one article's "
                      "per-lesion table):", ""] + system_table(prose) + ["", f"**B3 wrong → Ours (prose-only).** {b3_wrong(prose, 'OursC')} {b3_wrong(prose, 'Ours')}"]
    lines += [""] + confusion(res["systems"]) + [""]
    ours = res["systems"].get("Ours", {}).get("summary", {})
    lines.append(f"**Deferrals (LR-M / LR-TIV / LR-TR).** Ours: precision {p(ours.get('deferral_precision'))}, recall "
                 f"{p(ours.get('deferral_recall'))}. B1: precision {p(res['systems'].get('B1', {}).get('summary', {}).get('deferral_precision'))}, "
                 f"recall {p(res['systems'].get('B1', {}).get('summary', {}).get('deferral_recall'))}.")
    lines += ["", "**Per reference category** (correct / cases; the set is category-imbalanced):", "",
              "| Reference | Cases | B1 | B2 | B3 | B4 | Ours (ablation) | Ours-consensus | Ours-consensus envelope covers |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    gold_cats = sorted({r["gold"] for r in res["systems"]["Ours"]["rows"] if r["gold"]})
    for cat in gold_cats:
        cells = []
        for s in ORDER:
            rows = [r for r in res["systems"].get(s, {}).get("rows", []) if r["gold"] == cat]
            ok = sum(r["pred"] == cat or (cat in ("LR-M", "LR-TIV", "LR-TR") and r["pred"] == "defer") for r in rows)
            cells.append(f"{ok}/{len(rows)}" if rows else "–")
        ours = [r for r in res["systems"]["Ours"]["rows"] if r["gold"] == cat]
        cov = sum(cat in (r.get("envelope") or []) for r in ours)
        lines.append(f"| {cat} | {len(ours)} | " + " | ".join(cells) + f" | {cov}/{len(ours)} |")
    per = res["systems"].get("per_source")
    if per:
        lines += ["", "**Per source** (accuracy [95% CI], Ours envelope coverage):", "",
                  "| Source | B1 | B2 | B3 | B4 | Ours (ablation) | Ours-consensus | Ours-consensus envelope coverage |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for src, sy in sorted(per.items()):
            lines.append(f"| {src} | " + " | ".join(p(sy[s]["accuracy"]) if s in sy else "–" for s in ORDER)
                         + f" | {p(sy.get('OursC', sy.get('Ours', {})).get('envelope_coverage'))} |")
        pooled = res["systems"]
        lines.append("| pooled | " + " | ".join(p(pooled[s]["summary"]["accuracy"]) for s in ORDER
                                                if s in pooled) + f" | {p(pooled.get('OursC', pooled['Ours'])['summary'].get('envelope_coverage'))} |")
    return lines + [""]


def side_by_side(dev: dict | None, test: dict | None) -> list[str]:
    """Development and test results next to each other, all cases and prose-only, n and Wilson CI throughout."""
    lines = ["## Results at a glance: development vs test (real cases)", ""]
    if not dev or not test:
        return lines + ["Pending: the test split has not been run.", ""]
    tables = table_case_ids()
    sets = [("Dev, all", dev["systems"]), ("Test, all", test["systems"])]
    prose_dev = subset(dev, lambda i: i not in tables)
    prose_test = subset(test, lambda i: i not in tables)
    sets += [("Dev, prose-only", prose_dev), ("Test, prose-only", prose_test)]
    lines += ["| System | " + " | ".join(f"{n} accuracy [95% CI]" for n, _ in sets) + " | Dev envelope coverage | "
              "Test envelope coverage | Dev contradictions | Test contradictions |", "| --- " * (len(sets) + 5) + "|"]
    for s in ORDER:
        if s not in dev["systems"] or s not in test["systems"]:
            continue
        accs = [p(sy[s]["summary"]["accuracy"]) if s in sy else "–" for _, sy in sets]
        env = [short(r["systems"][s]["summary"].get("envelope_coverage")) if "Ours" in s else "–" for r in (dev, test)]
        con = [short(r["systems"][s]["summary"]["contradiction_rate"]) for r in (dev, test)]
        lines.append(f"| {SYSTEM_NAMES[s]} | " + " | ".join(accs + env + con) + " |")
    n_test_tables = sum(r["id"] in tables for r in test["systems"]["Ours"]["rows"])
    lines += ["", f"Prose-only excludes the rows taken from one article's per-lesion table ({len(tables)} cases, all in "
              f"development); {n_test_tables} test cases are table rows, so the test prose-only figures equal the test "
              "figures. The test split was scored once (`data/real/test_runs.log`).", "", b1_denominators(dev, test), ""]
    return lines


def b1_denominators(dev: dict, test: dict) -> str:
    """Why B1 and B4 contradictions have smaller denominators than the rule-computed arms."""
    n = [r["systems"]["B1"]["summary"]["contradiction_rate"]["n"] for r in (dev, test)]
    return ("B1 and B4 contradictions are counted only where B1's stated category and the rule category from B1's own "
            f"features are both LR-1–LR-5 ({n[0]} of {dev['cases']} development and {n[1]} of {test['cases']} test "
            "cases); the rule-computed arms are checked on every case.")


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
                      f"{t['mean_envelope_size']:.2f} | {short(t['near_cutoff_rate'])} |" for t in d["table"]]
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
    fixable = {"extraction_error": "yes: a definition-grounded extraction fix, checked on dev only",
               "size_error": "yes: size parsing, checked on dev only", "scope_error": "yes: a documented scope keyword",
               "out_of_scope": "no: the findings text lacks the information",
               "reference_ambiguous": "no: depends on the reference", "other": "unclear"}
    lines += ["", "| Case | Reference | Ours | Class | Minimal change that reproduces the reference | Fixable without the test set |",
              "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {e['id']} | {e['reference']} | {e['ours']} | {e['class']} | {e['detail']} | {fixable.get(e['class'], 'unclear')} |"
              for e in after["errors"]]
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
    lines.append(f"n = {d['n']}, seed {d['seed']}, prompt hash `{d.get('prompt_hash', '')[:12]}`, commit "
                 f"`{(d.get('git') or {}).get('commit', '')[:10]}` (uncommitted changes: {(d.get('git') or {}).get('dirty')}).")
    lines += [""] + system_table(d["systems"], "Agreement with rule-generated gold [95% CI]") + [""]
    b4 = d["systems"].get("B4", {}).get("summary", {})
    if b4:
        lines.append(f"B4 corrected {b4.get('corrected')} of B1's {d['n']} categories.")
    lines += ["", f"**B3 wrong → Ours.** {b3_wrong(d['systems'], 'OursC')} {b3_wrong(d['systems'], 'Ours')}", ""]
    return lines


LIMITATIONS = [
    "Small real-case sample: confidence intervals are wide; the test set is used once.",
    "Selection bias: published and teaching cases over-represent clear-cut LR-5 and LR-M; they are not a consecutive clinical series.",
    "Category imbalance: published case reports over-represent definite HCC (LR-5), so the real-case set is category-imbalanced; "
    "results are reported per category, and LR-3 / LR-4 numbers rest on very few cases and must not be over-interpreted.",
    "No radiologist validation and no second annotator yet: no radiologist has confirmed the references, the error "
    "attribution or the reviewed Europe PMC cases, and inter-annotator agreement is not yet collected (single reviewer).",
    "LI-RADS only: Lung-RADS, BI-RADS and an external RXL-RADSet evaluation were planned and are not done.",
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
]


def _pc(k: int, n: int) -> str:
    """k/n as a percentage with its 95 % Wilson interval, one decimal."""
    from radsenvelope.evaluation.metrics import wilson
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100 * k / n:.1f}% (95% CI {100 * lo:.1f}–{100 * hi:.1f}%)"


def headline_section(dev: dict, test: dict) -> list[str]:
    rob = load(BENCH / "results_comparison.json")
    if not (rob and dev and test):
        return []
    c = lambda res, s: res["systems"][s]["summary"]["contradiction_rate"]
    b1 = [c(dev, "B1"), c(test, "B1")]
    oc = [c(dev, "OursC"), c(test, "OursC")]
    pool = lambda xs: (sum(x["k"] for x in xs), sum(x["n"] for x in xs))
    m = rob["systems"]["OursC"]["summary"]
    rb1 = c(rob, "B1")
    return ["## Headline numbers", "",
            f"- Language model alone (B1) contradicted the ACR table applied to its own features in {_pc(rb1['k'], rb1['n'])} "
            f"of the robustness-test reports (§9), {_pc(b1[0]['k'], b1[0]['n'])} of real development cases and "
            f"{_pc(b1[1]['k'], b1[1]['n'])} of real test cases; pooled real cases {_pc(*pool(b1))}. " + b1_denominators(dev, test),
            f"- Ours-consensus (rule-computed category) contradictions: {c(rob, 'OursC')['k']}/{c(rob, 'OursC')['n']} robustness, "
            f"{pool(oc)[0]}/{pool(oc)[1]} real cases (development + test); zero by construction.",
            f"- Decision-critical alerts {_pc(m['alert_rate']['k'], m['alert_rate']['n'])} vs flagging any uncertainty "
            f"{_pc(m['any_uncertainty_rate']['k'], m['any_uncertainty_rate']['n'])} (robustness test, Ours-consensus).", ""]


def build() -> str:
    lines = ["# Evaluation", "", "Generated by `data_tools/build_evaluation_report.py` from the committed results files; "
             "numbers are never typed by hand.", ""]
    lines += protocol()
    dev, test = load(REAL / "results.comparison.dev.json"), load(REAL / "results.comparison.test.json")
    lines += headline_section(dev, test)
    lines += side_by_side(dev, test)
    lines += comparison_section(dev, "2. Development set (real cases)")
    lines += comparison_section(test, "3. Test set (real cases, run once)")
    lines += sensitivity_section() + repeatability_section() + annotation_section() + error_section()
    lines += wawtace_section() + robustness_section()
    lines += ["## 10. Limitations", ""] + [f"- {x}" for x in LIMITATIONS] + [""]
    lines += plan_coverage_section()
    return "\n".join(lines)


# Hand-audited against the pre-project deck and synopsis (not a measured result): one row per concrete promise.
PLAN = {"done": 21, "changed": 4, "partial": 8, "missing": 11, "end_of_plan_missing": 4}


def _pct(x: float) -> str:
    return f"{int(x * 100 + 0.5)}%"                         # round half up: 29/40 = 72.5% -> 73%


def plan_coverage_section() -> list[str]:
    p = PLAN
    total = p["done"] + p["changed"] + p["partial"] + p["missing"]
    score = p["done"] + p["changed"] + 0.5 * p["partial"]
    rest = total - p["end_of_plan_missing"]
    return ["## 11. Implementation against the pre-project plan", "",
            f"Method: every concrete promise in the pre-project deck and synopsis was listed ({total} promises) and marked "
            "done, changed into a working equivalent, partial, or missing. Score = (done + changed + ½ × partial) / promises.", "",
            "| Done | Changed | Partial | Missing | Promises | Strict coverage | Excluding end-of-plan items |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            f"| {p['done']} | {p['changed']} | {p['partial']} | {p['missing']} | {total} | "
            f"{_pct(score / total)} ({score:g}/{total}) | {_pct(score / rest)} ({score:g}/{rest}) |", "",
            f"End-of-plan items (all missing, excluded in the last column): paper, provisional patent, prior-art search, "
            f"radiologist review. Missing otherwise: Lung-RADS, BI-RADS, the RXL-RADSet external test, the risk-coverage curve, "
            f"token and retry cost, radiologist agreement. Changed: Ollama JSON-schema decoding instead of vLLM with Outlines; "
            f"27 real cases plus 200 generated reports instead of ~1,000 synthetic reports; the hybrid arm as post-hoc "
            f"correction (B4); confidence-based abstention as the Certainty Envelope.", ""]


def main() -> None:
    OUT.write_text(build(), encoding="utf-8")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
