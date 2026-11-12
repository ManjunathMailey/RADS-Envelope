"""
LLM extractor: a local model served by Ollama, constrained to the Extraction JSON schema.

The model reads text and fills feature states with verbatim evidence. It never assigns a
category. `sample()` draws several stochastic extractions for the self-consistency estimate
used in consensus.py.
"""
from __future__ import annotations

import os
import time

from .schema import Extraction

MODEL = os.environ.get("RADS_MODEL", "qwen2.5:7b-instruct")
KEEP_ALIVE = "60m"
THINKING_PREFIXES = ("qwen3", "deepseek-r1", "gpt-oss")
SAMPLE_TEMPERATURE = 0.7

SYSTEM = """You extract LI-RADS imaging features for ONE liver observation from a radiology report.
For each feature return a state and the exact supporting words.
- present: the report states the feature is there.
- absent: the report explicitly says it is not there (e.g. "no washout").
- uncertain: hedged language ("possible", "probable", "questionable", "subtle", "equivocal", "cannot be excluded").
- not_documented: the feature is not mentioned at all.
Definitions:
- aphe = NONRIM arterial phase hyperenhancement. Rim arterial phase hyperenhancement or rim enhancement is NOT aphe: state absent.
- washout = nonperipheral washout. Peripheral washout is NOT washout: state absent.
- capsule = enhancing capsule.
- growth = threshold growth versus prior imaging. "No prior imaging" means not_documented. "Stable" or "unchanged" means absent.
- af_malignant = ancillary features favouring malignancy (e.g. restricted diffusion, mild-moderate T2 hyperintensity, fat in mass).
- af_benign = ancillary features favouring benignity (e.g. size stability over 2 years, marked T2 hyperintensity).
- size_mm = largest diameter in millimetres (convert cm to mm). Use only a number written in the report.
  size_mm must be the exact number written, with its decimal point (e.g. "9.5 mm" -> 9.5, "2.5 cm" -> 25).
  If no numeric size is written (e.g. only "small"), size_mm must be null. Never estimate a size.
- size_evidence = the exact size words from the report (e.g. "18 mm"), or "" if none.
- evidence must be copied word for word from the report as one continuous piece of text.
- When a feature is not_documented, its evidence must be the empty string "".
Never assign a LI-RADS category."""


def _error_text(e: Exception) -> str:
    msg = getattr(e, "error", None) or str(e) or type(e).__name__
    return f"{type(e).__name__}: {msg}"


def available(model: str = MODEL) -> tuple[bool, str]:
    try:
        import ollama
        listing = ollama.list()
        models = listing["models"] if "models" in listing else []
        names = [(m["model"] if "model" in m else m["name"]) for m in models]
        want = model if ":" in model else model + ":latest"
        if want not in names:
            return False, f"Model '{model}' is not installed. Run: ollama pull {model}"
        return True, model
    except Exception as e:
        return False, f"Ollama not reachable ({_error_text(e)})"


def _chat(text: str, temperature: float, seed: int | None, model: str) -> Extraction:
    import ollama
    options = {"temperature": temperature}
    if seed is not None:
        options["seed"] = seed
    kwargs = dict(model=model,
                  messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
                  format=Extraction.model_json_schema(), options=options, keep_alive=KEEP_ALIVE)
    if model.lower().startswith(THINKING_PREFIXES):
        kwargs["think"] = False
    try:
        resp = ollama.chat(**kwargs)
    except Exception as e:
        raise RuntimeError(_error_text(e)) from e
    content = resp["message"]["content"] if isinstance(resp, dict) else resp.message.content
    return Extraction.model_validate_json(content)


def extract(text: str, model: str = MODEL) -> tuple[Extraction, float]:
    """One deterministic extraction (temperature 0)."""
    t = time.time()
    return _chat(text, 0.0, None, model), time.time() - t


def sample(text: str, k: int, model: str = MODEL) -> tuple[list[Extraction], float]:
    """The deterministic extraction plus k-1 stochastic ones with fixed seeds (reproducible)."""
    t = time.time()
    out = [_chat(text, 0.0, None, model)]
    out += [_chat(text, SAMPLE_TEMPERATURE, 1000 + i, model) for i in range(k - 1)]
    return out, time.time() - t
