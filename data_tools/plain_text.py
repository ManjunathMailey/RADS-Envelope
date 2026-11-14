r"""
Plain-word wording for the project documents: typographic symbols become words.

    .\.venv\Scripts\python.exe data_tools\plain_text.py README.md docs\ARCHITECTURE.md ...

Numbers, values and paths are unchanged; Mermaid arrow syntax (-->, -- yes -->) is ASCII and untouched.
build_evaluation_report.py applies plain() to everything it writes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_NUM = r"\d[\d.,]*%?"


def plain(text: str) -> str:
    t = text
    t = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    # section references: "§2, §3" -> "sections 2 and 3"; "§9" -> "section 9"
    t = re.sub(r"§\s?(\d+),\s*§\s?(\d+)", r"sections \1 and \2", t)
    t = re.sub(r"§\s?(\d+)", r"section \1", t)
    t = t.replace("κ", "kappa")
    t = t.replace("½ × ", "half of ").replace("½", "half")
    t = t.replace(" × ", " by ").replace("×", " by ")
    t = re.sub(r"≥\s?", "at least ", t)
    t = re.sub(r"≤\s?", "at most ", t)
    t = re.sub(r"±\s?", "plus or minus ", t)
    t = re.sub(r"≈\s?", "about ", t)
    t = t.replace(" → ", " to ").replace("→", " to ")
    # en dash between numbers -> "to" ("30.1–43.4%" -> "30.1 to 43.4%"); a lone en dash (empty cell) -> hyphen
    t = re.sub(rf"({_NUM})\s?–\s?(?=\d)", r"\1 to ", t)
    t = t.replace(" – ", ", ").replace("–", "-")
    t = t.replace(" · ", ", ").replace("·", ",")
    return t


def main(paths: list[str]) -> None:
    for p in map(Path, paths):
        old = p.read_text(encoding="utf-8")
        new = plain(old)
        if new != old:
            p.write_text(new, encoding="utf-8")
            print("updated", p)


if __name__ == "__main__":
    main(sys.argv[1:])
