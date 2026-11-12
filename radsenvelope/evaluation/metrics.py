"""Evaluation metrics for extraction, categorisation and envelope behaviour.

Implemented here without external dependencies: Wilson score intervals, Cohen's kappa
(unweighted, linear or quadratic weights), confusion matrices, LR-5 sensitivity/specificity,
and the per-system summary used by the baseline comparison.
"""
from __future__ import annotations

import math
from collections import defaultdict

from radsenvelope.engine.ruleset import rank

STATES = ("present", "absent", "uncertain", "not_documented")
KAPPA_LABELS = ("LR-2", "LR-3", "LR-4", "LR-5")
NUMERIC = ("LR-1", "LR-2", "LR-3", "LR-4", "LR-5")
Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> list[float] | None:
    """95% Wilson score interval for k successes in n trials; None when n == 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def proportion(k: int, n: int) -> dict:
    return {"k": k, "n": n, "value": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


def cohen_kappa(a: list, b: list, labels: list | tuple, weights: str | None = None) -> float | None:
    """Cohen's kappa between two raters over `labels` (ordered for weighted kappa).
    weights: None (unweighted), "linear" or "quadratic". Pairs with a label outside `labels`
    are ignored. Returns None when undefined (no pairs, or no expected disagreement)."""
    idx = {lab: i for i, lab in enumerate(labels)}
    pairs = [(idx[x], idx[y]) for x, y in zip(a, b) if x in idx and y in idx]
    k, n = len(labels), len(pairs)
    if n == 0 or k < 2:
        return None
    obs = [[0.0] * k for _ in range(k)]
    for i, j in pairs:
        obs[i][j] += 1
    row = [sum(obs[i]) for i in range(k)]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    def w(i, j):
        if weights == "quadratic":
            return (i - j) ** 2 / (k - 1) ** 2
        if weights == "linear":
            return abs(i - j) / (k - 1)
        return 0.0 if i == j else 1.0

    observed = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    expected = sum(w(i, j) * row[i] * col[j] for i in range(k) for j in range(k)) / (n * n)
    return None if expected == 0 else round(1 - observed / expected, 4)


def confusion_matrix(gold: list, pred: list, labels: list | tuple = KAPPA_LABELS) -> dict:
    """Rows = gold, columns = predicted; anything outside `labels` goes to "other"
    (deferred, not assignable, LR-M, ...)."""
    names = list(labels) + ["other"]
    pos = {lab: i for i, lab in enumerate(labels)}
    m = [[0] * len(names) for _ in names]
    for g, p in zip(gold, pred):
        m[pos.get(g, len(labels))][pos.get(p, len(labels))] += 1
    return {"labels": names, "matrix": m}


def _numeric(c) -> bool:
    return c in NUMERIC


def system_summary(rows: list[dict], envelope: bool = False) -> dict:
    """rows: gold, pred (category or status), envelope (list|None), critical, any_unresolved,
    consistent (bool|None), contradiction (bool|None). Accuracy is over every case with a
    numeric gold category; a missing or deferred prediction counts as wrong."""
    graded = [r for r in rows if _numeric(r["gold"])]
    n = len(graded)
    exact = sum(r["pred"] == r["gold"] for r in graded)
    band = [r for r in graded if _numeric(r["pred"])]
    within = sum(abs(rank(r["pred"]) - rank(r["gold"])) <= 1 for r in band)
    pos = [r for r in graded if r["gold"] == "LR-5"]
    neg = [r for r in graded if r["gold"] != "LR-5"]
    contra = [r["contradiction"] for r in rows if r.get("contradiction") is not None]
    consistent = [r["consistent"] for r in rows if r.get("consistent") is not None]
    deferral_cases = [r for r in rows if r["gold"] in ("LR-M", "LR-TIV", "LR-TR")]
    out = {
        "cases": len(rows), "graded": n,
        "accuracy": proportion(exact, n),
        "weighted_kappa": cohen_kappa([r["gold"] for r in graded], [r["pred"] for r in graded], KAPPA_LABELS, "quadratic"),
        "confusion": confusion_matrix([r["gold"] for r in graded], [r["pred"] for r in graded]),
        "lr5_sensitivity": proportion(sum(r["pred"] == "LR-5" for r in pos), len(pos)),
        "lr5_specificity": proportion(sum(r["pred"] != "LR-5" for r in neg), len(neg)),
        "pm1_band_coverage": proportion(within, n),
        "mean_pm1_band_size": round(sum(len({max(2, rank(r["pred"]) - 1), rank(r["pred"]), min(5, rank(r["pred"]) + 1)})
                                        for r in band) / len(band), 3) if band else None,
        "contradiction_rate": proportion(sum(contra), len(contra)) if contra else None,
        "consistency_verified": proportion(sum(consistent), len(consistent)) if consistent else None,
        "correct_deferrals": proportion(sum(r["pred"] in (r["gold"], "defer") for r in deferral_cases),
                                        len(deferral_cases)),
        "mean_seconds": round(sum(r.get("seconds") or 0 for r in rows) / len(rows), 3) if rows else None,
    }
    if envelope:
        with_env = [r for r in graded if r.get("envelope")]
        out.update(
            envelope_coverage=proportion(sum(r["gold"] in r["envelope"] for r in with_env), n),
            mean_envelope_size=round(sum(len(r["envelope"]) for r in with_env) / len(with_env), 3) if with_env else None,
            alert_rate=proportion(sum(bool(r.get("critical")) for r in rows), len(rows)),
            any_uncertainty_rate=proportion(sum(bool(r.get("any_unresolved")) or len(r.get("envelope") or []) > 1
                                                for r in rows), len(rows)),
        )
    return out


def feature_scores(pairs: list[tuple[dict, dict]], features: tuple[str, ...]) -> dict:
    """pairs = [(gold_states, predicted_states)]. Returns accuracy and macro-F1 per feature."""
    out = {}
    for k in features:
        tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
        correct = 0
        for gold, pred in pairs:
            g, p = gold.get(k), pred.get(k)
            correct += g == p
            if g == p:
                tp[g] += 1
            else:
                fp[p] += 1
                fn[g] += 1
        f1s = []
        for s in STATES:
            if tp[s] + fp[s] + fn[s] == 0:
                continue
            prec = tp[s] / (tp[s] + fp[s]) if tp[s] + fp[s] else 0.0
            rec = tp[s] / (tp[s] + fn[s]) if tp[s] + fn[s] else 0.0
            f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        out[k] = {"accuracy": round(correct / len(pairs), 3) if pairs else None,
                  "macro_f1": round(sum(f1s) / len(f1s), 3) if f1s else None}
    return out


def category_scores(rows: list[dict]) -> dict:
    """rows need gold_category, pred_category, gold_envelope, pred_envelope, gold_critical, pred_critical."""
    n = len(rows)
    if not n:
        return {}
    exact = sum(r["pred_category"] == r["gold_category"] for r in rows)
    within = sum(r["pred_category"] is not None and abs(rank(r["pred_category"]) - rank(r["gold_category"])) <= 1
                 for r in rows)
    env_exact = sum(r["pred_envelope"] == r["gold_envelope"] for r in rows)
    covered = sum(r["gold_category"] in (r["pred_envelope"] or []) for r in rows)
    tp = sum(r["pred_critical"] and r["gold_critical"] for r in rows)
    fp = sum(r["pred_critical"] and not r["gold_critical"] for r in rows)
    fn = sum(not r["pred_critical"] and r["gold_critical"] for r in rows)
    return {
        "n": n,
        "category_accuracy": round(exact / n, 3),
        "within_one": round(within / n, 3),
        "envelope_exact": round(env_exact / n, 3),
        "gold_in_envelope": round(covered / n, 3),
        "critical_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "critical_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "alert_rate": round(sum(r["pred_critical"] for r in rows) / n, 3),
        "any_uncertainty_rate": round(sum(len(r["pred_envelope"] or []) > 1 or r.get("pred_any_unresolved", False)
                                          for r in rows) / n, 3),
    }
