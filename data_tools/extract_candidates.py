r"""
Extract candidate real cases from harvested Europe PMC full texts.

    .\.venv\Scripts\python.exe data_tools\extract_candidates.py

Reads data\raw\europepmc\articles.json and the cached JATS XML. In the case-description sections
it finds sentences that state a LI-RADS CT/MRI category (sentences about ultrasound or CEUS are
skipped) and the liver-lesion CT/MRI paragraph they belong to. Writes
data\real\candidates_europepmc.csv with the columns of radiopaedia_cases.csv plus review_status
(left empty), source_paragraph and category_sentence.

findings_text is verbatim: only figure references and the sentences that state a category are
removed (whitespace is collapsed). Nothing is paraphrased. Every row needs human review before it
is merged with merge_reviewed.py.
"""
from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "europepmc"
OUT = ROOT / "data" / "real" / "candidates_europepmc.csv"
BASE_COLUMNS = ["id", "url", "author", "license", "modality", "findings_text", "radiologist_category",
                "collected_by", "collected_on", "notes"]
COLUMNS = BASE_COLUMNS + ["review_status", "source_paragraph", "category_sentence"]

CATEGORY = re.compile(r"\b(?:LI-?RADS|LR|Liver Imaging Reporting and Data System)\)?"
                      r"(?:\s*(?:v(?:ersion)?\s*)?20\d\d)?[\s:-]*"
                      r"(?:(?:category|cat\.?|score|classification|grade)\s*(?:was|of|is|=)?[\s:-]*)?"
                      r"(?:LR-?)?(?P<c>[1-5]|M|TIV|TR|NC)\b(?!\.\d|\d)", re.I)
ULTRASOUND = re.compile(r"\b(ultrasound|ultrasonograph\w*|sonograph\w*|CEUS|contrast-enhanced US)\b", re.I)
US_ABBR = re.compile(r"\bUS\b")
LIVER = re.compile(r"\b(liver|hepatic|segment|lobe|hepatocellular|HCC|nodule|lesion|observation|mass)\b", re.I)
MODALITY_CT = re.compile(r"\b(CT|computed tomography|CECT|MDCT)\b")
MODALITY_MR = re.compile(r"\b(MRI|MR imaging|MR|magnetic resonance|gadoxetic|hepatobiliary phase)\b", re.I)
FEATURE = re.compile(r"(arterial|wash-?\s?out|capsul|hyperenhanc|enhancement|hypervascular|portal venous|"
                     r"delayed phase|hepatobiliary|T2|diffusion)", re.I)
SKIP_SECTIONS = re.compile(r"(discussion|introduction|background|conclusion|review|literature|abstract|"
                           r"acknowledg|reference|funding|consent|ethic|author|conflict|declaration)", re.I)
FIGURE_TEXT = re.compile(r"\s*\((?:see\s+)?(?:Fig(?:ure)?s?\.?|Supplementary\s+Fig\w*\.?|Table)\s*[\w\s,.–\-−&and]*\)", re.I)
EMPTY_PARENS = re.compile(r"\(\s*(?:[,;–\-]|and|\s)*\)")
_ABBREV = re.compile(r"(?:\b(?:Fig|Figs|e\.g|i\.e|vs|approx|Dr|No|al|ca|resp|cf)\.|\b[A-Z]\.)$")


def _text(el, skip_xref=True) -> str:
    """Element text with figure/table cross-references removed."""
    parts = [el.text or ""]
    for child in el:
        tag = child.tag.split("}")[-1]
        if tag == "xref" and skip_xref and child.get("ref-type") in ("fig", "table", "supplementary-material"):
            pass
        elif tag in ("table-wrap", "fig", "graphic", "disp-formula"):
            pass
        else:
            parts.append(_text(child, skip_xref))
        parts.append(child.tail or "")
    return "".join(parts)


def clean(text: str) -> str:
    text = " ".join(text.split())
    text = FIGURE_TEXT.sub("", text)
    text = EMPTY_PARENS.sub("", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return " ".join(text.split())


def sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])", text)
    out: list[str] = []
    for s in raw:
        if out and _ABBREV.search(out[-1]):
            out[-1] = f"{out[-1]} {s}"
        else:
            out.append(s)
    return [s for s in out if s.strip()]


def stated_sentences(text: str) -> list[tuple[str, list[str], bool]]:
    """(sentence, categories, mentions_ultrasound) for every sentence that states a LI-RADS category."""
    out = []
    for s in sentences(text):
        cats = [f"LR-{m.group('c').upper()}" for m in CATEGORY.finditer(s)]
        if cats:
            out.append((s, cats, bool(ULTRASOUND.search(s) or US_ABBR.search(s))))
    return out


def category_sentences(text: str) -> list[tuple[str, list[str]]]:
    """(sentence, categories) for sentences stating a CT/MRI category usable as the gold label;
    sentences mentioning ultrasound or CEUS are not used for the label (but are still removed)."""
    return [(s, cats) for s, cats, us in stated_sentences(text) if not us]


def is_imaging_paragraph(text: str) -> bool:
    return bool(LIVER.search(text) and (MODALITY_CT.search(text) or MODALITY_MR.search(text)) and FEATURE.search(text))


def modality(text: str) -> str:
    ct, mr = bool(MODALITY_CT.search(text)), bool(MODALITY_MR.search(text))
    return "CT+MRI" if ct and mr else "CT" if ct else "MRI" if mr else ""


def case_paragraphs(root) -> list[tuple[str, list[str]]]:
    """(section title, [paragraph texts]) for body sections that are not discussion/introduction."""
    body = next((e for e in root.iter() if e.tag.split("}")[-1] == "body"), None)
    if body is None:
        return []
    out: list[tuple[str, list[str]]] = []

    def walk(el, title):
        paras = []
        for child in el:
            tag = child.tag.split("}")[-1]
            if tag == "sec":
                t = next((c for c in child if c.tag.split("}")[-1] == "title"), None)
                walk(child, clean(_text(t)) if t is not None else title)
            elif tag == "p":
                paras.append(clean(_text(child)))
        if paras and not SKIP_SECTIONS.search(title or ""):
            out.append((title, paras))

    walk(body, "")
    return out


def strip_sentences(text: str, remove: list[str]) -> str:
    return " ".join(s for s in sentences(text) if s not in remove).strip()


def candidates_for(article: dict, root) -> list[dict]:
    rows = []
    first_author = (article["authors"].split(",")[0] or "Unknown").strip().rstrip(".")
    author = f"{first_author} et al. ({article['journal']} {article['year']})".replace(" )", ")")
    for title, paras in case_paragraphs(root):
        for i, p in enumerate(paras):
            cats = category_sentences(p)
            if not cats:
                continue
            removed = [s for s, _, _ in stated_sentences(p)]          # every category statement goes
            findings, source = strip_sentences(p, removed), p
            if not is_imaging_paragraph(findings) and i > 0 and is_imaging_paragraph(paras[i - 1]):
                prev_stated = [s for s, _, _ in stated_sentences(paras[i - 1])]
                findings = strip_sentences(paras[i - 1], prev_stated)
                source = paras[i - 1] + "\n\n" + p
            if len(findings) < 60 or not is_imaging_paragraph(findings):
                continue
            all_cats = [c for _, cs in cats for c in cs]
            distinct = list(dict.fromkeys(all_cats))
            note = f"{article['pmcid']}; section: {title or '(untitled)'}"
            if len(distinct) > 1:
                note += f"; several categories stated ({', '.join(distinct)}): check which applies"
            dup = next((r for r in rows if r["findings_text"] == findings), None)
            if dup is not None:                                   # two statements about the same findings
                dup["category_sentence"] += " | " + " | ".join(s for s in removed if s not in dup["category_sentence"])
                dup["notes"] += f"; also stated: {', '.join(distinct)}"
                continue
            rows.append({
                "url": f"https://europepmc.org/article/PMC/{article['pmcid']}", "author": author,
                "license": article["license"].upper(),
                "modality": modality(findings), "findings_text": findings, "radiologist_category": distinct[-1],
                "collected_by": "data_tools/extract_candidates.py", "collected_on": date.today().isoformat(),
                "notes": note, "review_status": "", "source_paragraph": source,
                "category_sentence": " | ".join(removed),
            })
    return rows


def main() -> None:
    articles = json.loads((CACHE / "articles.json").read_text(encoding="utf-8"))
    rows, used = [], 0
    for a in articles:
        if not (a.get("license_ok") and a.get("fulltext")):
            continue
        try:
            root = ET.fromstring((CACHE / "xml" / f"{a['pmcid']}.xml").read_bytes())
        except (ET.ParseError, OSError):
            continue
        found = candidates_for(a, root)
        used += bool(found)
        rows += found
    for n, r in enumerate(rows, 1):
        r["id"] = f"EPMC-CAND-{n:04d}"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(json.dumps({"articles_with_fulltext": sum(bool(a.get("fulltext")) for a in articles),
                      "articles_with_candidates": used, "candidate_rows": len(rows), "output": str(OUT)}, indent=1))


if __name__ == "__main__":
    main()
