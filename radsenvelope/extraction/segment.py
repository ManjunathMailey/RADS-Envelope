"""
Report segmentation.

Splits a report into its findings and impression, then splits the findings into one block
per liver observation. Markers recognised at the start of a line: "Observation 2:",
"Lesion 1 -", "1." / "2)", and "Segment VI:" / "Segment 4a:". Text without markers is a
single observation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_IMPRESSION = re.compile(r"^\s*(impression|conclusion|summary)\s*:", re.I | re.M)
_MARKER = re.compile(
    r"^\s*(?:(?P<obs>(?:observation|lesion|nodule)\s*#?\s*(?P<n>\d+))"
    r"|(?P<num>\d{1,2})[.)]"
    r"|(?P<seg>segments?\s+(?P<segid>[ivx]+|\d[ab]?)(?:\s*/\s*(?:[ivx]+|\d[ab]?))?))\s*[:.\-)]?\s*",
    re.I | re.M)
_SEG_INLINE = re.compile(r"\bsegments?\s+([ivx]+|\d[ab]?)\b", re.I)
_STATED = re.compile(r"(?:LI-?RADS|LR)[\s:-]*(?:category\s*)?(?P<c>[1-5]|M|TIV|NC)\b", re.I)


@dataclass
class Segment:
    label: str
    text: str


def split_sections(report: str) -> tuple[str, str]:
    m = _IMPRESSION.search(report)
    if not m:
        return report.strip(), ""
    return report[:m.start()].strip(), report[m.end():].strip()


def _label(block: str, fallback: str) -> str:
    m = _SEG_INLINE.search(block)
    return f"Segment {m.group(1).upper()}" if m else fallback


def split_observations(findings: str) -> list[Segment]:
    marks = list(_MARKER.finditer(findings))
    if len(marks) < 2:
        return [Segment(_label(findings, "Observation 1"), findings.strip())]
    segs = []
    head = findings[:marks[0].start()].strip()
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(findings)
        block = findings[m.start():end].strip()
        if head and i == 0:
            block = f"{head} {block}"
        segs.append(Segment(_label(block, f"Observation {i + 1}"), block))
    labels = [s.label for s in segs]
    for i, s in enumerate(segs):                      # disambiguate repeated labels
        if labels.count(s.label) > 1:
            s.label = f"{s.label} ({i + 1})"
    return segs


def stated_categories(impression: str) -> list[str]:
    """Categories written in the report's own impression, in order of appearance."""
    return [f"LR-{m.group('c').upper()}" for m in _STATED.finditer(impression)]
