# Error analysis: development set

Development cases: 19. Disagreements with the radiologist's category: 7. Prompt hash: `7e69f08f6618`.

Each disagreement is attributed to the minimal change the deterministic engine needs to reproduce the reference (`data_tools/error_analysis.py`). This is a candidate explanation to be confirmed by a radiologist, not a ground-truth label. Test cases are never analysed.

| Class | Count |
| --- | --- |
| extraction_error | 5 |
| out_of_scope | 1 |
| scope_error | 1 |

| Case | Reference | Ours | Envelope | Class | Detail | Model evidence |
| --- | --- | --- | --- | --- | --- | --- |
| RP001 | LR-3 | LR-4 | LR-4/LR-5 | extraction_error | aphe: present -> absent; washout: present -> absent; af_benign: not_documented -> present | aphe: "nodular hypervascular lesions are present in the right hepatic lobe on the arterial phase"; washout: "on the portal venous phase, these lesions fade to background liver enhancement" |
| PMC002 | LR-3 | LR-4 | LR-4/LR-5 | extraction_error | growth: present -> absent; af_benign: not_documented -> present | growth: "In June 2021 the abdominal ultrasound revealed the growth of the nodule to a diameter of 29 mm." |
| EPMC001 | LR-5 | not_assignable | - | out_of_scope | the findings text states no size | - |
| EPMC009 | LR-M | not_assignable | - | scope_error | reference LR-M not deferred (ours not_assignable) | - |
| EPMC014 | LR-5 | LR-4 | LR-4 | extraction_error | aphe: absent -> present | - |
| EPMC018 | LR-5 | LR-4 | LR-4 | extraction_error | aphe: absent -> present | - |
| EPMC019 | LR-4 | LR-3 | LR-3/LR-4 | extraction_error | capsule: absent -> present; af_malignant: not_documented -> present | capsule: "Enhancing "Capsule": No" |
