# Changelog

## 1.3.0 (panel, 14 Nov 2026)

- **Evaluation protocol.** Real radiologist-reported cases with a frozen development/test split
  (tag `eval-freeze`); held-out cases are scored only on purpose and every such run is logged with
  its code version and prompt fingerprint.
- **Fair comparison.** The same local model asked directly for a category (B1) side by side with
  lexicon + rules (B2), model + rules (B3) and the full system, with confidence intervals and
  agreement statistics. A robustness test with rule-generated gold is reported separately and never
  as accuracy.
- **Real data.** Reviewed open-access case reports from Europe PMC; open CT datasets (WAW-TACE,
  HCC-TACE-Seg) for measured lesion sizes, a label-consistency check and CT previews; provenance
  for every file.
- **Clearer feature definitions** for washout, threshold growth and arterial hyperenhancement, each
  tied to the LI-RADS v2018 definition and to the development error that prompted it; fixed seed and
  context size for repeatable output.
- **Report check**, **one-click resolution with a suggested addendum** and **documentation
  completeness**, in the analyser and in batch mode with CSV export.
- **Landing page** at `/`; the analyser moved to `/app`. Landing v2: interactive example computed by the rule engine, result numbers read from the committed result files, dark mode, brand mark.
- **Ours-consensus** (pre-registered): the lexicon votes as a second extractor; disagreement becomes uncertain and widens the envelope. Test split scored once at `eval-freeze-4`.
- **Hybrid arm B4**, size units read from table headers, scope revision `scope.2` (tumour in vein as LR-TIV, treated observations, ultrasound-only).

## 1.2.0

- **Comparison with a prior study.** Threshold growth, subthreshold growth and size stability are
  computed by the rules from a prior CT or MRI, with measurement uncertainty; an explicit statement
  in the report is never overridden.
- **Size integrity guard.** The size used is always a size written in the report (a misread
  "9.5 mm" as 95 is corrected).
- **Editing a size redoes the prior comparison.**
- **HL7 FHIR R4 export** of the result.
- Wider scope guard: ring and rim enhancement are deferred as possible LR-M.

## 1.1.0

- Uploading .txt and .docx reports, batch checking, and the audit of stated versus computed
  categories.
- Thorough mode: the report is read three times and disagreement becomes explicit uncertainty.

## 1.0.0

- First version: LI-RADS CT/MRI v2018 category computed from extracted features, the Certainty
  Envelope with management-aware alerts and a decisive question, and an impression generated from
  the result and checked against it.
