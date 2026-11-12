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
- Paste a report or upload a .txt / .docx file; batch mode checks many reports at once
- Audit: stated impression vs computed category
- Evaluation on real radiologist-written cases and a controlled-ambiguity stress test
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
.\.venv\Scripts\python.exe -m radsenvelope.evaluation.benchmark --extractor llm     # stress test, LLM
.\.venv\Scripts\python.exe -m radsenvelope.evaluation.benchmark --extractor lexicon # stress test, baseline
.\.venv\Scripts\python.exe -m pytest                                               # tests
```

Real cases go in `data/real/radiopaedia_cases.csv` (one row per case, with source URL and author).
Results appear in the Evaluation view.

## Layout

```
radsenvelope/
  rules/lirads_ct_mri_v2018.yaml   versioned diagnostic table, growth rules, management, scope
  engine/                          ruleset (category + trace), envelope, longitudinal growth, exam summary
  extraction/                      segmentation, LLM, lexicon, consensus, grounding, scope
  generation/impression.py         rule-consistent impression + verification
  evaluation/                      real cases, stress-test generator, metrics, benchmark
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
