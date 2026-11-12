# Error analysis: development set, BEFORE the Phase 2 prompt changes

Development cases: 5. Disagreements with the radiologist's category: 3. Prompt hash: `0f7f213bf1dd`.

Each disagreement is attributed to the minimal change the deterministic engine needs to reproduce the reference (`data_tools/error_analysis.py`). This is a candidate explanation to be confirmed by a radiologist, not a ground-truth label. Test cases are never analysed.

| Class | Count |
| --- | --- |
| extraction_error | 3 |

| Case | Reference | Ours | Envelope | Class | Detail | Model evidence |
| --- | --- | --- | --- | --- | --- | --- |
| RP001 | LR-3 | LR-4 | LR-4/LR-5 | extraction_error | aphe: present -> absent; washout: present -> absent; af_benign: not_documented -> present | aphe: "Multiple new small (8 mm) nodular hypervascular lesions are present in the right hepatic lobe on the arterial phase."; washout: "On the portal venous phase, these lesions fade to background liver enhancement." |
| PMC001 | LR-5 | LR-4 | LR-4 | extraction_error | aphe: absent -> present | aphe: "the round-shaped hepatic mass showed arterial enhancement and delayed washout" |
| PMC002 | LR-3 | LR-4 | LR-4/LR-5 | extraction_error | growth: present -> absent; af_benign: not_documented -> present | growth: "growth of the nodule to a diameter of 29 mm" |
