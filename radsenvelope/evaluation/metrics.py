"""Evaluation metrics for extraction, categorisation and envelope behaviour."""
from __future__ import annotations

from collections import defaultdict

from radsenvelope.engine.ruleset import rank

STATES = ("present", "absent", "uncertain", "not_documented")


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
