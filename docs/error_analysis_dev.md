# Error analysis: development set

Development cases: 5. Disagreements with the radiologist's category: 2. Prompt hash: `7e69f08f6618`.

Each disagreement is attributed to the minimal change the deterministic engine needs to reproduce the reference (`data_tools/error_analysis.py`). This is a candidate explanation to be confirmed by a radiologist, not a ground-truth label. Test cases are never analysed.

| Class | Count |
| --- | --- |
| extraction_error | 2 |

| Case | Reference | Ours | Envelope | Class | Detail | Model evidence |
| --- | --- | --- | --- | --- | --- | --- |
| RP001 | LR-3 | LR-4 | LR-4/LR-5 | extraction_error | aphe: present -> absent; washout: present -> absent; af_benign: not_documented -> present | aphe: "nodular hypervascular lesions are present in the right hepatic lobe on the arterial phase"; washout: "on the portal venous phase, these lesions fade to background liver enhancement" |
| PMC002 | LR-3 | LR-4 | LR-4/LR-5 | extraction_error | growth: present -> absent; af_benign: not_documented -> present | growth: "In June 2021 the abdominal ultrasound revealed the growth of the nodule to a diameter of 29 mm." |
