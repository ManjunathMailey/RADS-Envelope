"""
Size integrity guard.

`parse_sizes` finds every measurement written with a unit ("9.5 mm", "2.5 cm", "2,5 cm",
"1.2 x 0.9 cm", "18mm", "18-mm") and converts it to millimetres; a multi-dimension measurement
counts as its largest dimension and numbers without a unit are ignored. `reconcile_size` checks
an extracted size against those written sizes: a language model may drop a decimal point
(9.5 -> 95), and the diagnostic table is keyed on size, so the value used must be one the report
actually states. Deterministic; applied by the pipeline to every extractor.
"""
from __future__ import annotations

import re

_NUM = r"\d+(?:[.,]\d+)?"
_UNIT = r"(?P<unit>mm|cm|millimet(?:er|re)s?|centimet(?:er|re)s?)\b"
_SIZE = re.compile(rf"(?<![\d.,])(?P<dims>{_NUM}(?:\s*(?:x|×|by)\s*{_NUM})*)\s*-?\s*{_UNIT}", re.I)
# Unit given by a label or table column header instead of after the number, e.g. "HCC Size (mm): 11.6",
# "Size (cm): 2.1", "diameter, mm: 18". The number itself is still taken verbatim from the text.
_LABELLED = re.compile(
    rf"\b(?:size|diameter|diam\.?|dimensions?|measurements?|length)\b[^:;=\n\d]{{0,30}}?"
    rf"[(\[,]\s*(?P<unit>mm|cm|millimet(?:er|re)s?|centimet(?:er|re)s?)\s*[)\]]?\s*[:=]\s*"
    rf"(?P<dims>{_NUM}(?:\s*(?:x|×|by)\s*{_NUM})*)(?![\d.,])(?!\s*-?\s*(?:mm|cm)\b)", re.I)
_TOL = 0.01


def _mm(dims_text: str, unit: str) -> float:
    dims = [float(d.replace(",", ".")) for d in re.findall(_NUM, dims_text)]
    factor = 10.0 if unit.lower().startswith("c") else 1.0
    return round(max(dims) * factor, 2)


def parse_sizes(text: str) -> list[dict]:
    """[{mm, span, text}] for every measurement with a unit (after the number, or in its label),
    in order of appearance."""
    text = text or ""
    out = [{"mm": _mm(m.group("dims"), m.group("unit")), "span": [m.start(), m.end()], "text": m.group(0)}
           for m in _SIZE.finditer(text)]
    taken = [s["span"] for s in out]
    for m in _LABELLED.finditer(text):
        span = [m.start("dims"), m.end("dims")]
        if any(a < span[1] and span[0] < b for a, b in taken):
            continue
        out.append({"mm": _mm(m.group("dims"), m.group("unit")), "span": span, "text": m.group(0)})
    return sorted(out, key=lambda s: s["span"][0])


def reconcile_size(size_mm: float | None, evidence: str, text: str) -> tuple[float | None, str, bool]:
    """Return (size_mm, size_evidence, corrected).

    Kept when it equals a size written in the evidence or in the observation text (within 0.01 mm).
    Otherwise replaced by the size written in the evidence, else the largest size written in the
    text, else None. An evidence size counts only if the observation text states it too: a
    fragment such as "5 cm" cut out of "2,5 cm" must not confirm a misread."""
    tx = parse_sizes(text)
    ev = [s for s in parse_sizes(evidence) if any(abs(s["mm"] - t["mm"]) <= _TOL for t in tx)]
    if size_mm is not None and any(abs(size_mm - s["mm"]) <= _TOL for s in ev + tx):
        return size_mm, evidence, False
    if ev:
        new, new_ev = max(s["mm"] for s in ev), evidence
    elif tx:
        best = max(tx, key=lambda s: s["mm"])
        new, new_ev = best["mm"], best["text"]
    else:
        new, new_ev = None, ""
    return new, new_ev, new != size_mm
