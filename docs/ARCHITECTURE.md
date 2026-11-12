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
| Category and decision trace | `engine/ruleset.py` | yes |
| Certainty Envelope, witnesses, decisive questions | `engine/envelope.py` | yes |
| Exam summary | `engine/exam.py` | yes |
| Rule-consistent impression and verification | `generation/impression.py` | yes |

The language model only fills a JSON schema. It never produces a category or the impression.

## 3. Feature model

Each feature takes one of four states: `present`, `absent`, `uncertain`, `not_documented`.
Ancillary features are optional in LI-RADS, so an undocumented ancillary feature is treated as not
applied. Size is an interval: the reported value plus or minus a tolerance (default 2 mm, matching
reported inter-reader measurement variability), widened further when repeated extractions disagree
on the size.

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
| Incomplete rule files are rejected at load time | `test_incomplete_ruleset_is_rejected` |

## 7. Evaluation protocol

1. **Real cases (primary).** Radiologist-written LI-RADS cases (Radiopaedia, CC BY-NC-SA, attributed
   per case). Metrics: exact and within-one agreement with the radiologist's category, share of
   radiologist categories inside the envelope, correct deferrals for LR-M / LR-TIV.
2. **Controlled-ambiguity stress test.** Reports generated from known feature vectors with varied
   phrasing, hedges, omissions and near-threshold sizes. Because the gold vector is known, the gold
   envelope is known. Metrics: per-feature macro-F1, category accuracy, envelope exact match,
   decision-critical precision and recall, and alert burden (management-aware alerts vs flagging
   every uncertainty). Run for the lexicon baseline and the LLM extractor.
3. **Planned.** MIMIC-IV-Note radiology reports (credentialed access; local inference only, as the
   data use agreement requires) and de-identified hospital reports under ethics approval.

## 8. Scope

In scope: untreated observations, LI-RADS CT/MRI v2018 core diagnostic table, one-step ancillary
adjustment. Deferred to the radiologist: LR-1 (definitely benign), LR-M, LR-TIV, treated
observations (LR-TR), ultrasound and CEUS LI-RADS.
