"""
Versioned, machine-readable categorisation rules.

A RuleSet is loaded from YAML, validated for completeness at load time, and exposes two
pure functions: `categorize` (features + size -> category) and `trace` (the same decision,
returned as the ordered list of rule steps that produced it).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RULES_DIR = Path(__file__).resolve().parents[1] / "rules"
DEFAULT_RULESET = "lirads_ct_mri_v2018.yaml"

FEATURES = ("aphe", "washout", "capsule", "growth", "af_malignant", "af_benign")
MAJOR_FEATURES = ("aphe", "washout", "capsule", "growth")
FEATURE_LABELS = {
    "aphe": "Nonrim arterial phase hyperenhancement",
    "washout": "Nonperipheral washout",
    "capsule": "Enhancing capsule",
    "growth": "Threshold growth",
    "af_malignant": "Ancillary features favouring malignancy",
    "af_benign": "Ancillary features favouring benignity",
}
SHORT_LABELS = {
    "aphe": "APHE", "washout": "washout", "capsule": "capsule", "growth": "threshold growth",
    "af_malignant": "AF-malignancy", "af_benign": "AF-benignity",
}


class RuleSetError(ValueError):
    """Raised when a rule file is incomplete or inconsistent."""


def rank(category: str) -> int:
    return int(category.split("-")[1])


@dataclass(frozen=True, eq=False)
class RuleSet:
    raw: dict

    # ---------- construction ----------
    @classmethod
    def load(cls, name: str = DEFAULT_RULESET) -> "RuleSet":
        with open(RULES_DIR / name, encoding="utf-8") as fh:
            rs = cls(yaml.safe_load(fh))
        rs.validate()
        return rs

    def validate(self) -> None:
        r = self.raw
        for key in ("system", "version", "size_cutoffs_mm", "size_buckets", "core_table",
                    "ancillary", "management", "category_meaning", "growth"):
            if key not in r:
                raise RuleSetError(f"missing key: {key}")
        self._validate_growth(r["growth"])
        if len(r["size_buckets"]) != len(r["size_cutoffs_mm"]) + 1:
            raise RuleSetError("size_buckets must have one more entry than size_cutoffs_mm")
        reachable = set()
        for aphe_key in ("nonrim_aphe", "no_aphe"):
            rows = r["core_table"].get(aphe_key)
            if rows is None:
                raise RuleSetError(f"core_table.{aphe_key} missing")
            for bucket in r["size_buckets"]:
                cells = rows.get(bucket)
                if not cells or len(cells) != 3:
                    raise RuleSetError(f"core_table.{aphe_key}.{bucket} must list 0, 1 and 2+ features")
                for c in cells:
                    reachable.update(c.values() if isinstance(c, dict) else [c])
        lo, hi = rank(r["ancillary"]["downgrade_floor"]), rank(max(reachable, key=rank))
        reachable.update(f"LR-{i}" for i in range(lo, hi + 1))
        for c in reachable:
            if c not in r["management"]:
                raise RuleSetError(f"no management entry for {c}")
            if c not in r["category_meaning"]:
                raise RuleSetError(f"no category_meaning entry for {c}")

    @staticmethod
    def _validate_growth(g) -> None:
        if not isinstance(g, dict):
            raise RuleSetError("growth must be a mapping")
        for key in ("threshold_percent", "threshold_max_days", "stability_min_days"):
            v = g.get(key)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                raise RuleSetError(f"growth.{key} must be a positive number")
        if g["stability_min_days"] <= g["threshold_max_days"]:
            raise RuleSetError("growth.stability_min_days must exceed growth.threshold_max_days")
        mods = g.get("valid_prior_modalities")
        if not mods or not isinstance(mods, list) or not all(isinstance(m, str) and m for m in mods):
            raise RuleSetError("growth.valid_prior_modalities must be a non-empty list of names")
        if g.get("unequivocal_change") != "size_tolerance":
            raise RuleSetError("growth.unequivocal_change must be 'size_tolerance'")

    # ---------- metadata ----------
    @property
    def label(self) -> str:
        return f"{self.raw['system']} {self.raw.get('modality', '')} v{self.raw['version']}".replace("  ", " ")

    @property
    def cutoffs(self) -> list[float]:
        return [float(c) for c in self.raw["size_cutoffs_mm"]]

    @property
    def categories(self) -> list[str]:
        return sorted(self.raw["management"], key=rank)

    def management(self, category: str) -> str:
        return self.raw["management"][category]

    def meaning(self, category: str) -> str:
        return self.raw["category_meaning"][category]

    def defer_keywords(self) -> dict:
        return self.raw.get("defer_keywords", {})

    @property
    def growth(self) -> dict:
        return self.raw["growth"]

    # ---------- decision ----------
    def bucket(self, size_mm: float) -> str:
        for cut, name in zip(self.cutoffs, self.raw["size_buckets"]):
            if size_mm < cut:
                return name
        return self.raw["size_buckets"][-1]

    def _core(self, f: dict, size_mm: float) -> tuple[str, dict]:
        row_key = "nonrim_aphe" if f["aphe"] else "no_aphe"
        bucket = self.bucket(size_mm)
        counted = [k for k in self.raw["additional_major_features"] if f[k]]
        cell = self.raw["core_table"][row_key][bucket][min(len(counted), 2)]
        special = None
        if isinstance(cell, dict):
            special = "capsule only" if f["capsule"] else "washout or threshold growth"
            cell = cell["capsule_only"] if f["capsule"] else cell["otherwise"]
        return cell, {"row": row_key, "bucket": bucket, "counted": counted, "special": special}

    def _ancillary(self, category: str, mal: bool, ben: bool) -> tuple[str, str]:
        anc = self.raw["ancillary"]
        if mal and ben:
            return category, "Both kinds present: no adjustment"
        r = rank(category)
        if mal:
            if r < rank(anc["upgrade_ceiling"]):
                return f"LR-{r + 1}", f"Favouring malignancy: upgrade by one (ceiling {anc['upgrade_ceiling']})"
            return category, f"Favouring malignancy: already at or above ceiling {anc['upgrade_ceiling']}"
        if ben:
            if r > rank(anc["downgrade_floor"]):
                return f"LR-{r - 1}", "Favouring benignity: downgrade by one"
            return category, f"Favouring benignity: already at floor {anc['downgrade_floor']}"
        return category, "None applied"

    def categorize(self, f: dict, size_mm: float) -> str:
        core, _ = self._core(f, size_mm)
        return self._ancillary(core, bool(f["af_malignant"]), bool(f["af_benign"]))[0]

    def trace(self, f: dict, size_mm: float) -> list[dict]:
        """Ordered rule steps that produce the category; rendered as the decision path in the UI."""
        core, info = self._core(f, size_mm)
        final, anc_note = self._ancillary(core, bool(f["af_malignant"]), bool(f["af_benign"]))
        n = len(info["counted"])
        steps = [
            {"step": "Arterial phase", "value": "Nonrim APHE" if f["aphe"] else "No nonrim APHE",
             "detail": "Selects the APHE row of the diagnostic table"},
            {"step": "Observation size", "value": f"{size_mm:g} mm -> {info['bucket']} mm",
             "detail": f"Cut-offs at {', '.join(f'{c:g}' for c in self.cutoffs)} mm"},
            {"step": "Additional major features",
             "value": f"{n} ({', '.join(SHORT_LABELS[k] for k in info['counted'])})" if n else "0 (none)",
             "detail": "Counted: nonperipheral washout, enhancing capsule, threshold growth"},
            {"step": "Diagnostic table", "value": core,
             "detail": f"{info['bucket']} mm, {'APHE' if f['aphe'] else 'no APHE'}, {min(n, 2)}{'+' if n >= 2 else ''} feature(s)"
                       + (f"; special cell: {info['special']}" if info["special"] else "")},
            {"step": "Ancillary features", "value": final, "detail": anc_note},
        ]
        return steps


@lru_cache(maxsize=8)
def get_ruleset(name: str = DEFAULT_RULESET) -> RuleSet:
    return RuleSet.load(name)
