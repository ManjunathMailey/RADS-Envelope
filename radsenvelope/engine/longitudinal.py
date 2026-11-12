"""
Longitudinal reasoning: threshold growth, subthreshold growth and size stability from a prior study.

Pure functions. Every number comes from the `growth` section of the rule file. Measurement
uncertainty is handled the same way as in the Certainty Envelope: the percent change is
evaluated at both ends of the tolerance interval (current - tol vs prior + tol, and
current + tol vs prior - tol). Growth is `present` only if the threshold is met at every end,
`uncertain` if it is met at some ends but not others, and `absent` if it is met at none.

`compare()` never raises: invalid or incomplete input gives `not_documented` with a reason.
"""
from __future__ import annotations

from datetime import date

from .envelope import ABSENT, NOT_DOCUMENTED, PRESENT, UNCERTAIN
from .ruleset import RuleSet, get_ruleset

_MODALITY_ALIASES = {"CT": "CT", "MR": "MRI", "MRI": "MRI", "US": "Ultrasound", "ULTRASOUND": "Ultrasound",
                     "CEUS": "Ultrasound"}
_EPS = 1e-9


def normalise_modality(name) -> str:
    key = str(name or "").strip().upper()
    return _MODALITY_ALIASES.get(key, str(name or "").strip())


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def _pct(cur: float, prior: float) -> float:
    return (cur / prior - 1.0) * 100.0 if prior > 0 else float("inf")


def _mm(x: float) -> str:
    return f"{x:g}"


def compare(current_mm, current_date, prior_mm, prior_date, prior_modality, tolerance_mm: float,
            ruleset: RuleSet | None = None) -> dict:
    """Compare one observation with its prior measurement. Returns a JSON-serialisable dict."""
    g = (ruleset or get_ruleset()).growth
    modality = normalise_modality(prior_modality)
    tol = max(float(tolerance_mm or 0.0), 0.0)
    out = {
        "growth_state": NOT_DOCUMENTED, "af_malignant": False, "af_benign": False,
        "percent_change": None, "percent_range": None, "interval_days": None,
        "rule": "", "explanation": "", "measurement_dependent": False, "source": "prior",
        "current_mm": current_mm, "prior_mm": prior_mm, "prior_modality": modality,
        "tolerance_mm": tol,
    }

    valid = {m.upper() for m in g["valid_prior_modalities"]}
    if modality.upper() not in valid:
        names = " or ".join(g["valid_prior_modalities"])
        why = ("Ultrasound priors cannot be used for LI-RADS growth" if modality == "Ultrasound"
               else f"Prior modality '{modality or 'unknown'}' cannot be used for LI-RADS growth")
        return {**out, "rule": "prior_modality_invalid",
                "explanation": f"{why}; growth needs a prior {names}."}

    d_cur, d_prior = _as_date(current_date), _as_date(prior_date)
    if d_cur is None or d_prior is None:
        return {**out, "rule": "invalid_date",
                "explanation": "An exam date is missing or not a valid date, so growth cannot be computed."}
    days = (d_cur - d_prior).days
    out["interval_days"] = days
    if days <= 0:
        return {**out, "rule": "invalid_interval",
                "explanation": "The prior exam is not dated before the current exam, so growth cannot be computed."}
    if not current_mm or not prior_mm or current_mm <= 0 or prior_mm <= 0:
        return {**out, "rule": "missing_size",
                "explanation": "A size is missing on the current or the prior study, so growth cannot be computed."}

    cur, prior = float(current_mm), float(prior_mm)
    point = _pct(cur, prior)
    low = _pct(max(cur - tol, 0.0), prior + tol)
    high = _pct(cur + tol, prior - tol) if prior - tol > 0 else float("inf")
    out.update(percent_change=round(point, 1),
               percent_range=[round(low, 1), None if high == float("inf") else round(high, 1)])

    thr, max_days = float(g["threshold_percent"]), int(g["threshold_max_days"])
    within = days <= max_days
    met_low, met_high = low >= thr - _EPS, high >= thr - _EPS
    sizes = f"from {_mm(prior)} to {_mm(cur)} mm ({point:+.0f}%) in {days} days"
    tol_txt = f"±{_mm(tol)} mm"

    if within and met_low:
        return {**out, "growth_state": PRESENT, "rule": "threshold_growth",
                "explanation": f"Grew {sizes}: at least {thr:g}% within {max_days} days even allowing "
                               f"{tol_txt} measurement error, so threshold growth is present."}
    if within and met_high:
        hi_txt = "more" if high == float("inf") else f"{high:+.0f}%"
        return {**out, "growth_state": UNCERTAIN, "rule": "threshold_growth_uncertain",
                "measurement_dependent": True, "source": "measurement",
                "explanation": f"Grew {sizes}: within {tol_txt} measurement error the change ranges from "
                               f"{low:+.0f}% to {hi_txt}, so threshold growth depends on the measurement."}

    out["growth_state"] = ABSENT
    if cur - prior > tol + _EPS:
        reason = (f"longer than {max_days} days, so it" if (not within and point >= thr - _EPS)
                  else "below the threshold, so it")
        return {**out, "af_malignant": True, "rule": "subthreshold_growth",
                "explanation": f"Grew {sizes}: an unequivocal increase {reason} counts as subthreshold "
                               f"growth, an ancillary feature favouring malignancy."}
    if abs(cur - prior) <= tol + _EPS and days >= int(g["stability_min_days"]):
        return {**out, "af_benign": True, "rule": "size_stability",
                "explanation": f"Size {_mm(prior)} to {_mm(cur)} mm over {days} days, unchanged within "
                               f"{tol_txt} for at least {int(g['stability_min_days'])} days: size stability, "
                               f"an ancillary feature favouring benignity."}
    return {**out, "rule": "no_threshold_growth",
            "explanation": f"Size {sizes.replace('from ', '', 1)}: no threshold growth."}
