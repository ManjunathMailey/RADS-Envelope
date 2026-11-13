r"""
Slide figures from the committed result files (no number is typed by hand).

    .\.venv-data\Scripts\python.exe data_tools\make_figures.py

Writes 300 dpi PNGs with a white background and no titles into docs\figures\:
  fig_accuracy_dev_test.png   accuracy with 95 % Wilson CIs, all arms, development vs test (real cases)
  fig_contradiction.png       share of cases whose category contradicts the system's own features
  fig_alerts.png              decision-critical alerts vs flagging any uncertainty (robustness test)
  fig_confusion_real.png      Ours-consensus confusion matrix on development + test real cases
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures"
INK, MUTED, LINE, ACCENT, LIGHT = "#1d1d1f", "#6e6e73", "#e3e3e8", "#0071e3", "#a1a1a6"
NAMES = {"B1": "B1\nLLM-direct", "B2": "B2\nlexicon+rules", "B3": "B3\nLLM+rules", "B4": "B4\nhybrid",
         "Ours": "Ours\nLLM-only", "OursC": "Ours-\nconsensus"}
ORDER = ("B1", "B2", "B3", "B4", "Ours", "OursC")
FONT = ["Inter", "Segoe UI", "DejaVu Sans"]


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(LINE)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.label.set_color(MUTED)
    ax.grid(axis="y", color=LINE, linewidth=0.6)
    ax.set_axisbelow(True)


def save(fig, name):
    fig.savefig(OUT / name, dpi=300, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print("->", OUT / name)


def accuracy(dev, test):
    fig, ax = plt.subplots(figsize=(9, 4.2))
    width, xs = 0.38, range(len(ORDER))
    for j, (res, label, colour) in enumerate(((dev, "Development (n=16)", LIGHT), (test, "Test (n=7)", INK))):
        vals, lo, hi = [], [], []
        for s in ORDER:
            a = res["systems"][s]["summary"]["accuracy"]
            vals.append(a["value"])
            lo.append(a["value"] - a["ci95"][0])
            hi.append(a["ci95"][1] - a["value"])
        pos = [x + (j - 0.5) * width for x in xs]
        bars = ax.bar(pos, vals, width, color=colour, label=label, zorder=2)
        ax.errorbar(pos, vals, yerr=[lo, hi], fmt="none", ecolor=MUTED, elinewidth=1, capsize=3, zorder=3)
        for b, s in zip(bars, ORDER):
            a = res["systems"][s]["summary"]["accuracy"]
            ax.text(b.get_x() + b.get_width() / 2, 0.02, f"{a['k']}/{a['n']}", ha="center", va="bottom", fontsize=7,
                    color="white" if colour == INK else INK)
    ax.set_xticks(list(xs), [NAMES[s] for s in ORDER])
    for t, s in zip(ax.get_xticklabels(), ORDER):
        if s == "OursC":
            t.set_color(ACCENT)
            t.set_fontweight("bold")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Accuracy (95% Wilson CI)")
    ax.legend(frameon=False, fontsize=9, labelcolor=MUTED, loc="upper left")
    style(ax)
    save(fig, "fig_accuracy_dev_test.png")


def contradiction(rob, dev):
    groups = [("Robustness test\n(rule-generated gold)", rob), ("Real development cases", dev)]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    for i, (label, res) in enumerate(groups):
        b1 = res["systems"]["B1"]["summary"]["contradiction_rate"]
        rule = res["systems"]["OursC"]["summary"]["contradiction_rate"]
        for j, (val, txt, colour) in enumerate(((b1, "LLM-direct (B1)", INK), (rule, "Rule-computed (B2, B3, Ours)", ACCENT))):
            x = i + (j - 0.5) * 0.36
            ax.bar(x, val["value"], 0.34, color=colour, label=txt if i == 0 else None, zorder=2)
            ax.text(x, val["value"] + 0.02, f"{val['k']}/{val['n']}\n{val['value']:.1%}", ha="center", va="bottom",
                    fontsize=8, color=INK)
    ax.set_xticks([0, 1], [g for g, _ in groups])
    ax.set_ylim(0, 0.62)
    ax.set_ylabel("Category contradicts own features")
    ax.legend(frameon=False, fontsize=9, labelcolor=MUTED, loc="upper right")
    style(ax)
    save(fig, "fig_contradiction.png")


def alerts(rob):
    m = rob["systems"]["OursC"]["summary"]
    vals = [("Decision-critical alerts\n(management changes)", m["alert_rate"], ACCENT),
            ("Flag any uncertainty", m["any_uncertainty_rate"], LIGHT)]
    fig, ax = plt.subplots(figsize=(6, 3.2))
    for i, (label, p, colour) in enumerate(vals):
        ax.barh(i, p["value"], 0.55, color=colour, zorder=2)
        ax.text(p["value"] + 0.01, i, f"{p['k']}/{p['n']}  ({p['value']:.0%})", va="center", fontsize=9, color=INK)
    ax.set_yticks([0, 1], [v[0] for v in vals])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel("Share of 200 robustness-test reports")
    style(ax)
    ax.grid(axis="x", color=LINE, linewidth=0.6)
    ax.grid(axis="y", visible=False)
    save(fig, "fig_alerts.png")


def confusion(dev, test):
    gold_labels = ["LR-2", "LR-3", "LR-4", "LR-5", "LR-M / TIV"]
    pred_labels = ["LR-2", "LR-3", "LR-4", "LR-5", "deferred", "not assignable"]
    gold_map = lambda g: g if g in ("LR-2", "LR-3", "LR-4", "LR-5") else "LR-M / TIV"
    pred_map = lambda p: p if p in ("LR-2", "LR-3", "LR-4", "LR-5") else ("deferred" if p == "defer" else "not assignable")
    rows = dev["systems"]["OursC"]["rows"] + test["systems"]["OursC"]["rows"]
    full = [[0] * len(pred_labels) for _ in gold_labels]
    for r in rows:
        full[gold_labels.index(gold_map(r["gold"]))][pred_labels.index(pred_map(r["pred"]))] += 1
    keep_r = [i for i in range(len(gold_labels)) if any(full[i])]
    keep_c = [j for j in range(len(pred_labels)) if any(full[i][j] for i in range(len(gold_labels)))]
    m = [[full[i][j] for j in keep_c] for i in keep_r]
    row_names, names = [gold_labels[i] for i in keep_r], [pred_labels[j] for j in keep_c]
    fig, ax = plt.subplots(figsize=(5.6, 3.9))
    vmax = max(max(row) for row in m) or 1
    ax.imshow(m, cmap=matplotlib.colors.LinearSegmentedColormap.from_list("n", ["#ffffff", ACCENT]), vmin=0, vmax=vmax)
    for i, row in enumerate(m):
        for j, v in enumerate(row):
            ax.text(j, i, str(v), ha="center", va="center", fontsize=10, color="white" if v > vmax * 0.55 else INK)
    ax.set_xticks(range(len(names)), names, rotation=0, fontsize=8, color=MUTED)
    ax.set_yticks(range(len(row_names)), row_names, fontsize=8, color=MUTED)
    ax.set_xlabel(f"Ours-consensus (n = {len(rows)} real cases, development + test)", color=MUTED, fontsize=8)
    ax.set_ylabel("Radiologist reference", color=MUTED, fontsize=8)
    for s in ax.spines.values():
        s.set_color(LINE)
    save(fig, "fig_confusion_real.png")


def main():
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = FONT
    dev, test = load("data/real/results.comparison.dev.json"), load("data/real/results.comparison.test.json")
    rob = load("data/benchmark/results_comparison.json")
    accuracy(dev, test)
    contradiction(rob, dev)
    alerts(rob)
    confusion(dev, test)


if __name__ == "__main__":
    main()
