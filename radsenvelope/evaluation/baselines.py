"""
Baseline B1, "LLM-direct": the answer to "why not just ask the LLM?".

The same local model is asked, in one call constrained to a JSON schema, for the LI-RADS v2018
features AND a final category, with a compact v2018 summary in the system prompt. Nothing
checks its category. Comparing that category with our engine applied to the model's OWN
features gives its internal contradiction rate; our pipeline's rate is zero by construction
(the category is computed from the features), which the impression consistency check verifies.
"""
from __future__ import annotations

import json
import time
from typing import Literal

from pydantic import Field, ValidationError

from radsenvelope.engine.ruleset import FEATURES
from radsenvelope.extraction import llm
from radsenvelope.extraction.schema import Extraction
from radsenvelope.pipeline import run_observation

CATEGORIES = ("LR-1", "LR-2", "LR-3", "LR-4", "LR-5", "LR-M", "LR-TIV", "not_assignable")

SYSTEM_DIRECT = llm.SYSTEM.replace("Never assign a LI-RADS category.", "") + """
Then assign the final ACR LI-RADS CT/MRI v2018 category in "category", for a patient at high risk of HCC.
LI-RADS v2018 CT/MRI summary:
- Additional major features: nonperipheral washout, enhancing capsule, threshold growth.
- Without nonrim APHE: <20 mm -> LR-3 with 0 or 1 additional feature, LR-4 with 2 or more;
  >=20 mm -> LR-3 with 0, LR-4 with 1 or more.
- With nonrim APHE: <10 mm -> LR-3 with 0, LR-4 with 1 or more;
  10-19 mm -> LR-3 with 0, LR-4 if the only additional feature is capsule, LR-5 if it is washout or
  threshold growth, LR-5 with 2 or more; >=20 mm -> LR-4 with 0, LR-5 with 1 or more.
- Ancillary features favouring malignancy may upgrade by one category, but not to LR-5;
  ancillary features favouring benignity downgrade by one. Both kinds present: no adjustment.
- An uncertain (hedged) feature is treated as absent.
- Rim APHE or targetoid appearance -> LR-M. Tumour in vein -> LR-TIV.
- If no size is written, category is "not_assignable"."""


class DirectAnswer(Extraction):
    category: Literal[CATEGORIES] = Field(description="Final LI-RADS v2018 category")


def _chat(text: str, model: str) -> str:
    """One deterministic call to the local model; returns the raw JSON text."""
    import ollama
    kwargs = dict(model=model, messages=[{"role": "system", "content": SYSTEM_DIRECT},
                                         {"role": "user", "content": text}],
                  format=DirectAnswer.model_json_schema(), options={"temperature": 0.0}, keep_alive=llm.KEEP_ALIVE)
    if model.lower().startswith(llm.THINKING_PREFIXES):
        kwargs["think"] = False
    resp = ollama.chat(**kwargs)
    return resp["message"]["content"] if isinstance(resp, dict) else resp.message.content


def llm_direct(text: str, model: str | None = None, tolerance: float = 2.0) -> dict:
    """Run B1 on one observation's findings text.

    Returns category (or None if the answer could not be parsed), features, size_mm, the
    engine's category for those same features (engine_category) and contradiction:
    True/False when both categories are numeric LR-1..LR-5, otherwise None."""
    t = time.time()
    out = {"category": None, "features": None, "size_mm": None, "engine_category": None,
           "contradiction": None, "error": None}
    try:
        ans = DirectAnswer.model_validate_json(_chat(text, model or llm.MODEL))
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        out.update(error=f"unparseable answer: {type(e).__name__}", seconds=round(time.time() - t, 3))
        return out
    except Exception as e:                                   # model not reachable, etc.
        out.update(error=f"LLM call failed: {type(e).__name__}: {e}", seconds=round(time.time() - t, 3))
        return out
    states = {k: getattr(ans, k).state for k in FEATURES}
    engine = run_observation("B1", states, ans.size_mm, tolerance, True, [])
    engine_cat = engine.get("acr_category")
    numeric = lambda c: c is not None and c.startswith("LR-") and c[-1].isdigit()
    out.update(category=ans.category, features=states, size_mm=ans.size_mm, engine_category=engine_cat,
               contradiction=(ans.category != engine_cat) if numeric(ans.category) and numeric(engine_cat) else None,
               seconds=round(time.time() - t, 3))
    return out
