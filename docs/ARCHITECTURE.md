# RADS-Envelope: design notes

## 1. Problem

LI-RADS assigns a liver observation to a category (LR-1 to LR-5, LR-M, LR-TIV) from a small set of
imaging features. Two failure modes matter in practice:

1. **Contradiction.** A report's impression states a category that its own findings do not support.
   Free-text generation by language models makes this more likely, not less.
2. **Hidden uncertainty.** Hedged findings ("possible washout"), undocumented features and sizes near
   a cut-off are collapsed into one confident category. The ACR tie-break rule (treat an uncertain
   feature as absent) produces a valid category, but it does not tell the reader that a different,
   clinically important category was one finding away.

Published hybrid systems (LLM extraction followed by rule-based scoring; Gu et al. 2024 for LI-RADS,
Bhayana et al. 2025 for O-RADS) address the first problem. RADS-Envelope addresses both.

## 2. Pipeline

| Stage | Module | Deterministic |
| --- | --- | --- |
| Segment findings and impression; one block per observation | `extraction/segment.py` | yes |
| Extract four-state features with verbatim evidence | `extraction/llm.py`, `extraction/lexicon.py` | LLM: no |
| Self-consistency consensus | `extraction/consensus.py` | yes, given samples |
| Grounding and scope guard | `extraction/schema.py`, `extraction/scope.py` | yes |
| Comparison with a prior study (optional) | `engine/longitudinal.py`, `pipeline.py` | yes, given sizes |
| Category and decision trace | `engine/ruleset.py` | yes |
| Certainty Envelope, witnesses, decisive questions | `engine/envelope.py` | yes |
| Exam summary | `engine/exam.py` | yes |
| Rule-consistent impression and verification | `generation/impression.py` | yes |
| FHIR R4 export | `export/fhir.py` | yes |

The language model only fills a JSON schema. It never produces a category or the impression.

## 3. Feature model

Each feature takes one of four states: `present`, `absent`, `uncertain`, `not_documented`.
Ancillary features are optional in LI-RADS, so an undocumented ancillary feature is treated as not
applied. Size is an interval: the reported value plus or minus a tolerance (default 2 mm, matching
reported inter-reader measurement variability), widened further when repeated extractions disagree
on the size.

**Size integrity guard.** The table is keyed on size, and a language model can drop a decimal point
(9.5 mm read as 95). `extraction/sizes.py` parses every size the report writes with a unit
("9.5 mm", "2,5 cm", "1.2 x 0.9 cm"; largest dimension; cm converted). Each extraction draw is
checked before consensus: a size the observation text does not state is replaced by the written
size from its evidence, else the largest written size, else null, and the original value is kept
as `corrected_from`. The same guard applies to prior-report sizes.

## 4. Certainty Envelope

Let `U` be the set of unresolved features and `I` the size interval. The envelope is

    E = { category(f, s) : f is any completion of U, s in I }

Because the rule table is piecewise constant in size, it is enough to evaluate the interval end
points, the reported size, and the two sides of every cut-off inside the interval. With six binary
features the enumeration is at most 2^6 x 5 = 320 rule evaluations, so `E` is computed exactly, in
well under a millisecond.

For every category in `E` the engine also returns a **witness**: the completion with the fewest
departures from the ACR point assumption (hedged features are cheaper assumptions than undocumented
ones). This is what the UI shows as "LR-5 if washout present".

**Management divergence.** Each category maps to a management class. An observation is flagged
*decision-critical* only when `E` spans more than one class. Uncertainty that cannot change
management is shown but does not raise an alert.

**Decisive question.** For each unresolved item `u`, the engine computes the envelope with `u`
fixed to present and to absent and ranks items by the expected reduction in management classes.
Near a cut-off the question is "re-measure".

## 5. Two sources of uncertainty

* **Report uncertainty**: the radiologist hedged. The extractor returns `uncertain`.
* **Extractor uncertainty**: with self-consistency enabled, the model is sampled `k` times
  (one greedy run plus seeded samples at temperature 0.7). A feature on which the samples
  contradict each other, or agree on fewer than two thirds, becomes `uncertain`.

Both enter the envelope through the same state, so the envelope bounds the effect of the report's
ambiguity and of the extractor's own instability. Each feature records which source applies.

## 6. Guarantees and how they are tested

| Property | Test |
| --- | --- |
| Rule table equals an independent transcription for all 64 feature vectors x 7 sizes | `test_table_matches_reference` |
| Core category is monotone in size and in each major feature | `test_core_table_is_monotone` |
| Envelope is sound and complete: equal to a brute-force envelope over a 0.05 mm size grid, for all 256 state combinations at five size/tolerance settings | `test_envelope_sound_and_complete` |
| The point category is in the envelope and has a zero-assumption witness | `test_point_category_and_witnesses` |
| Answering a decisive question never widens the envelope | `test_decisive_answer_never_widens_envelope` |
| Generated impression states exactly the engine's category, for every state combination | `test_impression_consistent_for_all_state_combinations` |
| Incomplete rule files are rejected at load time | `test_incomplete_ruleset_is_rejected`, `test_missing_or_invalid_growth_section_is_rejected` |
| Growth rule boundaries: exactly 50 %, 183 days and 730 days; ultrasound priors refused | `tests/test_longitudinal.py` |
| The size used is always a size written in the report (a misread 95 for "9.5 mm" is corrected) | `tests/test_sizes.py` |
| An explicit growth statement in the report is never overridden by the prior comparison | `test_explicit_report_statement_is_kept_and_conflict_flagged` |
| FHIR export: every reference resolves, the category equals the engine's for every sample, no standard codes are invented | `tests/test_fhir.py` |

## 7. Evaluation protocol

1. **Real cases (primary).** Radiologist-written LI-RADS cases (Radiopaedia, CC BY-NC-SA, attributed
   per case). Metrics: exact and within-one agreement with the radiologist's category, share of
   radiologist categories inside the envelope, correct deferrals for LR-M / LR-TIV.
2. **Controlled-ambiguity stress test.** Reports generated from known feature vectors with varied
   phrasing, hedges, omissions and near-threshold sizes. Because the gold vector is known, the gold
   envelope is known. Metrics: per-feature macro-F1, category accuracy, envelope exact match,
   decision-critical precision and recall, and alert burden (management-aware alerts vs flagging
   every uncertainty). Run for the lexicon baseline and the LLM extractor.
3. **Baselines: "why not just ask the LLM?"** Every case is run through four systems:
   B1 *LLM-direct* (the same local model returns features and a category in one schema-constrained
   call with a compact v2018 summary; `evaluation/baselines.py`), B2 lexicon + rules, B3 LLM + rules
   (point category only) and Ours (LLM + rules + envelope). Reported per system: accuracy, LR-5
   sensitivity and specificity, ±1-band coverage and envelope coverage, all with 95 % Wilson
   intervals; quadratic-weighted Cohen's kappa over LR-2..LR-5; a confusion matrix; mean envelope
   size; alert rate. B1's *internal contradiction rate* compares its category with the engine
   applied to its own features; for the rule-based systems it is zero by construction, and the
   impression consistency check is reported as evidence. Optional feature-level gold columns
   (`gold_aphe`, ..., `gold_size_mm`) give per-feature F1 on real cases;
   `data_tools/annotator_kappa.py` measures inter-annotator agreement on them.
4. **Planned.** MIMIC-IV-Note radiology reports (credentialed access; local inference only, as the
   data use agreement requires) and de-identified hospital reports under ethics approval.

## 8. Scope

In scope: untreated observations, LI-RADS CT/MRI v2018 core diagnostic table, one-step ancillary
adjustment. Deferred to the radiologist: LR-1 (definitely benign), LR-M, LR-TIV, treated
observations (LR-TR), ultrasound and CEUS LI-RADS.

## 9. Longitudinal reasoning

Threshold growth is the major feature most often left undocumented, yet it follows from two
measurements and two dates. When a prior report is supplied, the pipeline segments and extracts it
with the same extractor, keeps only its sizes, and pairs observations by segment label, falling back
to report order only when one side has no segment label. `engine/longitudinal.py` then applies the
v2018 definitions, whose numbers live in the `growth` section of the rule file:

* **Threshold growth** (major): increase of at least 50 % in at most 183 days, against a prior CT
  or MRI. Ultrasound priors are refused.
* **Subthreshold growth** (ancillary, favours malignancy): an unequivocal increase that does not
  meet threshold growth.
* **Size stability** (ancillary, favours benignity): no unequivocal change over at least 730 days.

A change is unequivocal when it exceeds the observation's size tolerance. As in the envelope, the
percent change is evaluated at both ends of the tolerance interval: the threshold met at every end
gives `present`, at some ends `uncertain` (source: measurement), at none `absent`. An uncertain
result enters the envelope like any other unresolved feature.

**Merge policy.** The computed state fills in growth that the report leaves undocumented or hedged.
An explicit statement in the report is kept; if the computation disagrees, a `prior_conflict`
warning is shown instead of silently overriding the radiologist. Ancillary flags are OR-ed with
the extracted ones. Each observation carries a `longitudinal` block (sizes, percent change,
interval, rule, explanation, matching method, conflict), and the impression gains one line per
compared observation. The line states no category, so the consistency check is unchanged.

**Re-computation.** The block also stores the prior measurement, dates, modality, the report's own
states and the states the merge produced. When the radiologist edits the size or the tolerance
changes, `/api/recompute` repeats the comparison and the merge: features that still hold their
merged value restart from the report's value, while a feature edited by hand counts as an explicit
statement and is kept, with a conflict warning if the prior disagrees.

## 10. FHIR export

`export/fhir.py` maps an analysis to an HL7 FHIR R4 Bundle of type `collection`: one
`DiagnosticReport` (status `preliminary`, conclusion = generated impression, `result` referencing
each observation) and one `Observation` per liver observation. The Observation carries the ACR
category (or the status when no category is assigned) as `valueCodeableConcept`, the segment as
`bodySite`, and components for size (UCUM `mm`), each feature state, the certainty envelope,
decision-critical and, when present, the longitudinal comparison (UCUM `%` and `d`). A
decision-support disclaimer is attached as a note. Resource ids are `urn:uuid` values derived
deterministically from the report, so the same analysis always produces the same bundle.

`POST /api/export/fhir` re-runs the engine on the posted features before exporting, so the bundle
states the rule-based category even if the client sends a stale or edited one.

Concepts are identified by `code.text` and local codes in `urn:radsenvelope:code`; only the HL7
category codes `RAD` and `imaging` are used. Mapping to LOINC, SNOMED CT and RadLex is future work
and is not approximated with invented codes.
