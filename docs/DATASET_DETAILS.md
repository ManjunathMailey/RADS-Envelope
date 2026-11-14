# Dataset details

Every figure in this document was read from the files in the repository on 14 Nov 2026 (row counts, record counts,
byte sizes, columns, rule-file contents). Nothing is estimated. Sizes are in bytes, with KB = 1,024 bytes.

## 1. Key figures

| Item | Value | Read from |
| --- | --- | --- |
| Real cases | 27 (3 Radiopaedia, 2 PMC, 22 Europe PMC) | `data/real/radiopaedia_cases.csv` (27 rows), id prefixes RP, PMC, EPMC |
| Development / test | 19 development, 8 test | `data/real/split.csv`, column `split` |
| Cases forced into development | 19 of the 19 development cases have a recorded reason | `split.csv`, column `forced_dev_reason` |
| Category mix, all 27 | LR-5 17, LR-3 3, LR-4 3, LR-M 3, LR-TIV 1 | `radiopaedia_cases.csv`, column `radiologist_category` |
| Category mix, development | LR-5 13, LR-3 2, LR-M 2, LR-4 1, LR-TIV 1 | `split.csv` joined with the case file |
| Category mix, test | LR-5 4, LR-4 2, LR-3 1, LR-M 1 | `split.csv` joined with the case file |
| Rows taken from one per-lesion table | 11 (notes contain "table cells"; all in development) | `radiopaedia_cases.csv`, column `notes` |
| Manifest entries | 990 | `data/manifest.csv` |
| Manifest verification (this copy) | 956 verified, 0 missing, 24 changed | `data_tools/verify_manifest.py` (see section 3) |
| Generated reports, robustness test | 200, seed 7, 1 sample per report | `data/benchmark/results_comparison.json`, keys `n`, `seed`, `samples` |
| Demo reports | 9 (S1 to S9) plus 1 longitudinal (S10) | `data/samples/reports.json`, `data/samples/longitudinal.json` |
| WAW-TACE patients | 233 | `data/real/wawtace_analysis.json` |
| WAW-TACE lesions with a label | 343 (LR-5 302, LR-4 24, LR-3 12, LR-M 5) | same file, `label_distribution` |
| Median size discrepancy (mask vs clinical diameter) | 4.3 mm (IQR 2.0 to 9.2 mm) | same file, `measurement_variability` |
| Lesions within 2 mm of a size cut-off (10 or 20 mm) | 67 of 343 = 19.5% | same file, `cutoff_proximity.within_2mm` |
| Lesions within the median discrepancy (4.3 mm) of a cut-off | 108 of 343 = 31.5% | same file, `cutoff_proximity.within_median_discrepancy` |
| Rule file | LI-RADS CT/MRI, version "2018", revision "scope.2" | `radsenvelope/rules/lirads_ct_mri_v2018.yaml` |

## 2. Files, grouped by source

Licence "project" means the file was produced by this project and is covered by the repository licence (MIT).

### 2.1 Real radiologist-reported cases (Radiopaedia, PMC, Europe PMC)

| Path | Format | Rows / records | Size | Used for | Origin | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| `data/real/radiopaedia_cases.csv` | CSV | 27 rows, 15 columns | 20,262 B (19.8 KB) | the 27 real evaluation cases: findings text and reference category | 5 cases entered by hand (Radiopaedia 3, PMC 2), plus 22 accepted Europe PMC candidates appended by `merge_reviewed.py` | per row: CC BY 18, CC BY-NC 4, CC BY-NC-SA 3.0 3, CC BY 4.0 2 |
| `data/real/split.csv` | CSV | 27 rows, 5 columns | 1,813 B (1.8 KB) | the frozen development/test split (tag `eval-freeze`) | `data_tools/split_real.py`, seed 2026 | project |
| `data/real/candidates_europepmc.csv` | CSV (git-ignored, local only) | 59 rows, 13 columns | 143,574 B (140.2 KB) | review sheet: 22 accept, 37 reject, from 42 articles | `data_tools/extract_candidates.py` | per row, as the source article |
| `data/real/annotations/annotator_a.csv` | CSV | 5 rows, 6 columns | 127 B | feature-level annotation template, annotator A (not yet filled) | project | project |
| `data/real/annotations/annotator_b.csv` | CSV | 5 rows, 6 columns | 127 B | feature-level annotation template, annotator B (not yet filled; identical to A by design) | project | project |
| `data/real/annotations/agreement.json` | JSON | 4 keys | 128 B | inter-annotator status: "not yet collected (single reviewer)", 0 rows filled, 5 matched ids | `data_tools/annotator_kappa.py` | project |

### 2.2 Evaluation results on the real cases (derived)

| Path | Format | Rows / records | Size | Used for | Origin | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| `data/real/results.comparison.dev.json` | JSON | 6 arms by 19 rows | 140,975 B (137.7 KB) | development results: B1, B2, B3, B4, Ours, Ours-consensus | `radsenvelope.evaluation.real_cases --compare --split dev`, then `compare.py` (Ours-consensus) | project |
| `data/real/results.comparison.test.json` | JSON | 6 arms by 8 rows | 62,535 B (61.1 KB) | held-out test results, scored once | same, with `RADS_RUN_TEST=1` | project |
| `data/real/test_runs.log` | JSON lines | 1 line | 417 B | the single logged test run: time, git state, model, prompt hashes | written by the test guard | project |
| `data/real/repeatability.dev.json` | JSON | 12 keys, per-case results over 6 runs | 9,641 B (9.4 KB) | repeatability (EVALUATION.md section 5) | `radsenvelope.evaluation.repeatability` | project |
| `data/real/tolerance_sensitivity.comparison.dev.json` | JSON | table of 4 tolerances | 2,067 B (2.0 KB) | size-tolerance sensitivity, development (section 4) | `radsenvelope.evaluation.sensitivity` | project |

### 2.3 Generated reports (robustness test) and demo samples

| Path | Format | Rows / records | Size | Used for | Origin | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| `data/benchmark/results_comparison.json` | JSON | 6 arms by 200 rows | 933,509 B (911.6 KB) | robustness test with rule-generated gold (section 9), landing page numbers, figures | `radsenvelope.evaluation.benchmark --n 200 --seed 7 --compare` | project |
| `data/benchmark/tolerance_sensitivity_comparison.json` | JSON | table of 4 tolerances | 2,101 B (2.1 KB) | size-tolerance sensitivity, robustness test (section 4) | `radsenvelope.evaluation.sensitivity` | project |
| `data/samples/reports.json` | JSON | 9 records (S1 to S9) | 2,881 B (2.8 KB) | demo reports in the app and in tests | written by the project (synthetic) | project |
| `data/samples/longitudinal.json` | JSON | 1 record (S10, with a prior study) | 489 B | demo of threshold growth from a prior study | written by the project (synthetic) | project |

The 200 generated reports are not stored as text. `radsenvelope/evaluation/generator.py` regenerates them
deterministically from seed 7, and the results file stores each report's id, gold category, prediction and features.

### 2.4 Open CT datasets (WAW-TACE, HCC-TACE-Seg, TCGA-LIHC)

| Path | Format | Rows / records | Size | Used for | Origin | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| `data/real/ct_lesion_sizes.csv` | CSV | 388 rows, 11 columns (WAW-TACE 378 masks from 233 patients; HCC-TACE-Seg 10 patients) | 70,462 B (68.8 KB) | lesion diameters measured from expert tumour masks, next to the dataset's clinical diameter | `data_tools/ct_lesions.py sizes` | derived from CC BY 4.0 data |
| `data/real/wawtace_analysis.json` | JSON | 9 keys | 3,561 B (3.5 KB) | measurement variability, cut-off proximity and size-label consistency (EVALUATION.md section 8) | `data_tools/wawtace_analysis.py` | derived from WAW-TACE, CC BY 4.0 |

### 2.5 Provenance

| Path | Format | Rows / records | Size | Used for | Origin | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| `data/manifest.csv` | CSV | 990 rows, 9 columns | 316,898 B (309.5 KB) | source, licence, retrieval time, sha256, size and record count of every downloaded file | `data_tools/build_manifest.py` | project |

Manifest rows by source: Europe PMC 936, HCC-TACE-Seg 36, WAW-TACE 10, TCGA-LIHC 4, and 4 status rows for
sources that were not downloaded (AMPLIFAI, MIMIC-IV-Note, Ramaiah hospital reports, PLC-CECT). Licences recorded:
CC BY 634, CC BY-NC 289, CC BY 4.0 37 (plus 10 written "cc-by-4.0"), CC BY-NC-SA 11, CC BY 3.0 / CC BY 4.0 4,
CC0 2, and 1 each gated, PhysioNet credentialed and institutional.

### 2.6 Figures (`docs/figures/`)

All PNG. Sizes in pixels are width by height.

| Path | Pixels | Size | Shows | Origin | Licence |
| --- | --- | --- | --- | --- | --- |
| `fig_accuracy_dev_test.png` | 2288 by 1142 | 87,386 B | accuracy with 95% CI, all arms, development vs test | `data_tools/make_figures.py` from the result files | project |
| `fig_contradiction.png` | 1823 by 1051 | 87,155 B | contradiction rate, B1 vs rule-computed arms | same | project |
| `fig_alerts.png` | 1902 by 922 | 50,558 B | decision-critical alerts vs flagging any uncertainty | same | project |
| `fig_confusion_real.png` | 1421 by 1072 | 56,682 B | Ours-consensus confusion matrix, real cases | same | project |
| `ct_preview_HCC_001.png` | 1129 by 728 | 295,020 B | arterial and portal phases with the expert tumour outline | `data_tools/ct_lesions.py preview` | derived from HCC-TACE-Seg, CC BY 4.0 |
| `ct_preview_HCC_002.png` | 1129 by 728 | 305,103 B | same, patient HCC_002 | same | same |
| `ct_preview_HCC_008.png` | 1129 by 728 | 368,723 B | same, patient HCC_008 | same | same |
| `app_01_landing.png` | 2880 by 7470 | 768,678 B | landing page, full length (device scale factor 2) | browser screenshot | project |
| `app_02_rp002_result.png` | 1440 by 1259 | 181,777 B | analyser on RP002 (real case) | browser screenshot | project; case text CC BY-NC-SA 3.0 |
| `app_03_s1_decision_critical.png` | 1440 by 1996 | 223,502 B | S1: decision-critical envelope and question | browser screenshot | project |
| `app_04_s1_after_present_addendum.png` | 1440 by 1362 | 162,421 B | S1 after answering Present, with addendum | browser screenshot | project |
| `app_05_s2_report_check.png` | 1440 by 1672 | 186,052 B | S2: report check "contradicts" | browser screenshot | project |
| `app_06_rp003_deferred.png` | 1440 by 1250 | 158,815 B | RP003 deferred (real case) | browser screenshot | project; case text CC BY-NC-SA 3.0 |
| `app_07_batch_samples.png` | 1440 by 1798 | 259,560 B | batch mode on the demo samples | browser screenshot | project |
| `app_08_fhir_export.png` | 1440 by 1259 | 184,208 B | FHIR export from a result | browser screenshot | project |
| `landing_v2_light_1440.png` | 1440 by 3735 | 339,648 B | landing page, light mode, desktop | browser screenshot | project |
| `landing_v2_dark_1440.png` | 1440 by 3735 | 336,495 B | landing page, dark mode, desktop | browser screenshot | project |
| `landing_v2_light_390.png` | 390 by 4978 | 291,096 B | landing page, light mode, phone width | browser screenshot | project |
| `landing_v2_dark_390.png` | 390 by 4978 | 289,351 B | landing page, dark mode, phone width | browser screenshot | project |
| `landing_v2_demo_after_present.png` | 552 by 583 | 47,948 B | landing example after answering Present | browser screenshot | project |
| `readme_hero.png` | 1440 by 780 | 161,728 B | README header image (crop of the landing page) | crop of `app_01_landing.png` | project |

### 2.7 Raw downloads (`data/raw/`, git-ignored)

On this machine `data/raw/` holds **990 files, 244,097,205 B (232.8 MB)**:

| Folder | Files | Size |
| --- | --- | --- |
| `europepmc/` | 963 | 148,503,693 B (141.6 MB): article index, query counts and cached full-text JATS XML |
| `hcc_tace_seg/` | 15 | 92,229,677 B (88.0 MB): clinical table, series list, DICOM SEG |
| `waw_tace/` | 7 | 2,390,278 B (2.3 MB): clinical table, CT metadata, tumour masks |
| `tcga_lihc/` | 5 | 973,557 B (0.9 MB): series list and clinical table, no images |

The manifest also records the HCC-TACE-Seg CT series. In this copy 24 of those series folders are empty
(see section 3), which is why the folder holds only 15 files.

## 3. Manifest verification

`data_tools/verify_manifest.py` recomputes the sha256 of every manifest row that has a local path; a DICOM series
folder is one row whose digest covers its files' sorted (name, sha256) list. On this copy: **956 verified, 0 missing,
24 changed**. All 24 changed rows are HCC-TACE-Seg CT series folders that are empty here: the manifest expects 1 to
274 DICOM files in each, and none are present. Those files were lost when the project was moved as a zip archive.
Nothing in the app, the tests or the evaluation reads them; they were used once to produce the three CT preview
figures, which are present.

## 4. Columns of each CSV

**`data/real/radiopaedia_cases.csv`** (the 27 real cases; the name is historical)

| Column | Holds |
| --- | --- |
| `id` | case id: RP001 to RP003 (Radiopaedia), PMC001 to PMC002, EPMC001 to EPMC022 (Europe PMC) |
| `url` | link to the source case or article |
| `author` | author or contributor of the source, for attribution |
| `license` | licence of that case's text |
| `modality` | imaging modality as stated: MRI 10, CT/MRI (see article) 11, CT+MRI 4, CT 2 |
| `findings_text` | the findings text the systems read, with every category statement removed |
| `radiologist_category` | the reference category stated by the reporting radiologist or authors |
| `collected_by` | who entered the row: a team member for the 5 hand-entered cases, `data_tools/extract_candidates.py` for the 22 Europe PMC cases |
| `collected_on` | date the row was entered (2026-11-13 for all 27) |
| `notes` | source remarks, for example that a row comes from a per-lesion table |
| `gold_aphe`, `gold_washout`, `gold_capsule`, `gold_growth` | optional feature-level reference states; empty for all 27 rows (no feature annotation yet) |
| `gold_size_mm` | optional reference size in mm; empty for all 27 rows |

**`data/real/split.csv`**

| Column | Holds |
| --- | --- |
| `id` | case id, as in the case file |
| `source` | radiopaedia, pmc or europepmc (dev/test: europepmc 14/8, radiopaedia 3/0, pmc 2/0) |
| `category` | reference category, used for stratification |
| `split` | dev or test |
| `forced_dev_reason` | why a case was forced into development (for example "article text shown during harvester development", 14 cases); empty for the 8 test cases |

**`data/real/candidates_europepmc.csv`** (local review sheet, git-ignored)

| Column | Holds |
| --- | --- |
| `id` ... `notes` | the same ten columns as the case file, from `id` to `notes` |
| `review_status` | the human decision: accept (22) or reject (37) |
| `source_paragraph` | the full CT/MRI paragraph the findings were taken from, for the reviewer |
| `category_sentence` | the sentence that stated the category (removed from `findings_text`) |

**`data/real/annotations/annotator_a.csv` and `annotator_b.csv`**

| Column | Holds |
| --- | --- |
| `id` | case id (the 5 hand-entered cases are prefilled) |
| `gold_aphe`, `gold_washout`, `gold_capsule`, `gold_growth` | the annotator's feature states |
| `gold_size_mm` | the annotator's size in mm |

**`data/real/ct_lesion_sizes.csv`**

| Column | Holds |
| --- | --- |
| `dataset` | WAW-TACE (378 rows) or HCC-TACE-Seg (10 rows) |
| `patient_id` | the dataset's patient id |
| `mask` | the mask file or SEG the measurement comes from |
| `phase` | contrast phase as given by the dataset (WAW-TACE codes are unverified against the dataset paper) |
| `segment` | which tumour or segment inside the mask |
| `measured_size_mm` | largest in-plane diameter of the largest connected tumour region |
| `slice_z_mm` | slice position of that diameter, where available |
| `region_area_mm2` | area of the region on that slice |
| `reference_size_mm` | the dataset's own clinical diameter, for comparison |
| `reference_source` | where the reference diameter comes from |
| `notes` | measurement remarks |

**`data/manifest.csv`**

| Column | Holds |
| --- | --- |
| `source` | dataset or source name |
| `url_or_doi` | download URL, DOI or series id |
| `license` | licence as published by the source |
| `retrieved_at` | retrieval time |
| `sha256` | content hash (for a DICOM series folder, a hash over its files' names and hashes) |
| `size_bytes` | size in bytes |
| `n_records` | records in the file (rows, articles or DICOM files) |
| `notes` | remarks, for example "requires login" |
| `local_path` | path under the repository; empty for sources that were not downloaded |

## 5. Rule file

`radsenvelope/rules/lirads_ct_mri_v2018.yaml`: system "LI-RADS", modality "CT/MRI", version "2018", revision "scope.2".

| Part | Content |
| --- | --- |
| Size cut-offs | 10 and 20 mm, giving 3 size buckets: under 10, 10 to 19, at least 20 mm |
| Diagnostic table | **18 cells**: 2 arterial-phase rows (nonrim APHE, no APHE) by 3 size buckets by 3 counts of additional major features (washout, capsule, threshold growth: none, one, two or more). One cell (nonrim APHE, 10 to 19 mm, one additional feature) splits into capsule only, LR-4, and otherwise, LR-5, so the table holds 19 outcomes |
| Ancillary features | upgrade ceiling, downgrade floor, rule for conflicting ancillary features |
| Tie-break | an uncertain feature counts as absent |
| Growth | threshold 50% within at most 183 days; stability at least 730 days; prior must be CT or MRI |
| Management | one recommendation each for LR-2, LR-3, LR-4, LR-5 |
| Scope gate | **11 keywords** (rim/ring enhancement and similar, targetoid, tumour in vein, post-treatment, ablation zone, TACE), **5 patterns** (tumour thrombus, enhancing soft tissue in vein, enhancing thrombus, treatment terms such as RFA, MWA, TARE, Y-90, SBRT, and "treated lesion/observation") and **1 condition** (ultrasound-only assessment). That is 17 scope rules in all |

## 6. Collection method and preprocessing

**Europe PMC (22 accepted cases).** `data_tools/harvest_europepmc.py` queried the public Europe PMC REST API with three
open-access queries:
- case reports mentioning LI-RADS: 207 hits;
- LI-RADS categories with CT or MRI: 769 hits;
- HCC with LI-RADS and APHE or washout: 927 hits.

Together that is 1,184 unique articles (`data/raw/europepmc/query_counts.json`). Of these, 941 had a licence allowing
research use: CC BY, CC BY-NC, CC BY-NC-SA or CC0. No-derivatives licences (222 CC BY-NC-ND) and articles without a
licence (21) were excluded, and 936 full texts were downloaded. Requests were limited to three per second with
backoff, and every response was cached. `data_tools/extract_candidates.py` searched the case-description sections for
sentences that state a LI-RADS CT/MRI category, skipping ultrasound and CEUS sentences, and took the liver-lesion
CT/MRI paragraph each belongs to. That produced 59 candidates from 42 articles. Each candidate was pre-screened with
AI assistance against a fixed checklist:
- CT/MRI LI-RADS v2018;
- imaging findings present in the text;
- reference category stated separately;
- at-risk liver;
- untreated observation;
- open licence.

A team member confirmed every decision: 22 accepted, 37 rejected. `data_tools/merge_reviewed.py` appended the
accepted rows to the case file as EPMC001 to EPMC022, skipping any duplicate of URL and text.

**Radiopaedia and PMC (5 cases).** These were entered by hand by a team member from the public case pages: findings
text, the radiologist's stated category, URL, author and licence for each row. No scraping was used.

**What was stripped from the findings text, and why.** In the accepted Europe PMC findings, the sentences that state a
category were removed, as were figure references, and whitespace was collapsed. Nothing else was changed or
paraphrased. The removed category sentence is kept in the review sheet's `category_sentence` column. The reason is
leakage: the systems must compute the category from the findings, so the text they read must not contain the answer.
The same rule applies to the hand-entered cases: `findings_text` holds the findings only, and the reference category
is in its own column.

**Split.** `data_tools/split_real.py` stratified the 27 cases by source and category with seed 2026 (target 40%
development, 60% test). Every case inspected during development was forced into development with the reason
recorded, which left 19 development and 8 test cases. The sorted test-id list has sha256 `d702feb4b6e7398b…`, and the
split is frozen under the tag `eval-freeze`.

**Open CT datasets.**
- **WAW-TACE:** the clinical table, CT metadata and tumour masks came from Zenodo record 12741586, with checksums
  verified. The CT image archives were deliberately not downloaded.
- **HCC-TACE-Seg and TCGA-LIHC:** fetched from NCI Imaging Data Commons with the official `idc-index` client. For
  HCC-TACE-Seg, the pre-treatment CT and expert segmentations of 10 patients; for TCGA-LIHC, metadata only.
- **Measurements:** lesion diameters are measured from the masks by `data_tools/ct_lesions.py`. No LI-RADS label is
  derived from any image; WAW-TACE labels are used exactly as published.
