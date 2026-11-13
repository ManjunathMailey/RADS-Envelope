# RADS-Envelope

Rule-consistent LI-RADS categorisation with certainty envelopes.

A local language model reads the radiology report and fills a structured schema. The ACR LI-RADS
rule table, loaded from a versioned file, computes the category. The **Certainty Envelope** then
shows every category the observation could still fall into given hedged findings, undocumented
features, size tolerance and extractor disagreement, and raises an alert only when those categories
lead to different patient management. The impression is generated from the rule output, so it
cannot contradict the findings.

Group 72 · Department of Computer Science and Engineering, M.S. Ramaiah University of Applied Sciences
Guide: Mr. Karthik D U

## Features

- Four-state feature extraction (present / absent / uncertain / not documented) with verbatim evidence and grounding check
- Self-consistency mode: repeated extractions; disagreement becomes explicit uncertainty
- Multi-observation reports with an exam-level summary
- Official ACR category with the full decision path
- Certainty Envelope with a witness for every reachable category
- Management-aware alerting and a single decisive question
- Rule-consistent impression generation with automatic verification
- Longitudinal reasoning: threshold growth, subthreshold growth and size stability computed by the rules from a prior CT or MRI, with measurement-aware uncertainty
- HL7 FHIR R4 export: a DiagnosticReport with one Observation per liver observation, ready for hospital integration
- Paste a report or upload a .txt / .docx file; batch mode checks many reports at once
- Report check: the category written in the report's own impression vs the rule-based category
  (consistent / contradicts / inside the envelope but not the ACR tie-break), with a word-level
  comparison of the stated and generated impressions
- One-click resolution: answer each decisive question (present / absent, or confirm the measurement),
  watch the envelope narrow, copy a suggested addendum sentence, undo the last answer
- Documentation completeness per observation (APHE, washout, capsule, size, and threshold growth when a
  prior study is given) with the missing items named; batch mean, most frequently missing item and
  CSV export
- Evaluation on real radiologist-written cases (frozen dev/test split) and a robustness test with rule-generated gold
- Fully offline: one laptop GPU, no report leaves the machine

## Quick start (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1     # once: venv, packages, model, tests
powershell -ExecutionPolicy Bypass -File .\run.ps1       # starts http://localhost:8000
```

Requires Python 3.10+ and [Ollama](https://ollama.com). Default model: `qwen2.5:7b-instruct`
(override with `$env:RADS_MODEL`). Without Ollama the app runs with the deterministic lexicon extractor.

## Evaluation

```powershell
.\.venv\Scripts\python.exe -m radsenvelope.evaluation.real_cases                  # real cases
.\.venv\Scripts\python.exe -m radsenvelope.evaluation.benchmark --extractor llm     # robustness test (rule-generated gold), LLM
.\.venv\Scripts\python.exe -m radsenvelope.evaluation.benchmark --extractor lexicon # robustness test, lexicon
.\.venv\Scripts\python.exe -m radsenvelope.evaluation.real_cases --compare        # B1 LLM-direct / B2 / B3 / Ours
.\.venv\Scripts\python.exe -m radsenvelope.evaluation.benchmark --compare         # same, on the robustness test
.\.venv\Scripts\python.exe -m pytest                                               # tests
```

Real cases go in `data/real/radiopaedia_cases.csv` (one row per case, with source URL and author).

Open-access case reports from Europe PMC (CC BY, CC BY-NC, CC0 only) can be harvested as review
candidates; downloads stay in the git-ignored `data/raw/`:

```powershell
.\.venv\Scripts\python.exe data_tools\harvest_europepmc.py      # search + full text, cached, <= 3 req/s
.\.venv\Scripts\python.exe data_tools\extract_candidates.py     # -> data/real/candidates_europepmc.csv
.\.venv\Scripts\python.exe data_tools\merge_reviewed.py         # append rows marked review_status=accept
```

Open CT datasets (WAW-TACE, HCC-TACE-Seg, TCGA-LIHC metadata) are fetched with the tools in
`data_tools/` from a separate environment (`.venv-data`, `data_tools/requirements-data.txt`);
`data/manifest.csv` records provenance and `data_tools/verify_manifest.py` re-checks every file.
See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
Results appear in the Evaluation view.

## Layout

```
radsenvelope/
  rules/lirads_ct_mri_v2018.yaml   versioned diagnostic table, growth rules, management, scope
  engine/                          ruleset (category + trace), envelope, longitudinal growth, exam summary
  extraction/                      segmentation, LLM, lexicon, consensus, grounding, scope
  generation/impression.py         rule-consistent impression + verification
  evaluation/                      real cases, robustness-test generator, metrics, baselines, protocol
  export/fhir.py                   HL7 FHIR R4 Bundle export
  api/app.py                       FastAPI service
  pipeline.py                      end-to-end pipeline shared by API, CLI and evaluation
web/                               browser client
tests/                             property and integration tests
docs/ARCHITECTURE.md               design, algorithm, guarantees, evaluation protocol
```

## Limitations

Research prototype for decision support. Not a medical device. Covers the LI-RADS CT/MRI v2018 core
table for untreated observations; LR-1, LR-M, LR-TIV, treated lesions and ultrasound LI-RADS are
deferred to the radiologist. Demo reports in `data/samples` are synthetic.
