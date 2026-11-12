r"""
Harvest open-access LI-RADS case reports from Europe PMC.

    .\.venv\Scripts\python.exe data_tools\harvest_europepmc.py [--max-pages N]

Uses the public Europe PMC REST API (no key). Searches for LI-RADS case reports, keeps only
articles licensed CC BY, CC BY-NC or CC0, and downloads their full-text JATS XML. At most three
requests per second, retries with exponential backoff, and every response is cached under
data\raw\europepmc\ (git-ignored), so a re-run makes no repeated requests.

Output: data\raw\europepmc\articles.json, one record per search hit with its license and
whether it passed the license filter and has full text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "europepmc"
SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
QUERY = '("LI-RADS" OR "LIRADS") AND ("case report" OR "case presentation") AND OPEN_ACCESS:y'
ALLOWED_LICENSES = {"cc by", "cc by-nc", "cc0"}
USER_AGENT = "rads-envelope-data-tools/1.0 (research prototype)"
MIN_INTERVAL = 1 / 3            # at most 3 requests per second
_last_request = [0.0]


def normalise_license(value) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").split())


def license_allowed(value) -> bool:
    return normalise_license(value) in ALLOWED_LICENSES


def _get(url: str, cache_file: Path, attempts: int = 5) -> bytes | None:
    """GET with cache, rate limit and exponential backoff. 404 returns None (cached as such)."""
    if cache_file.exists():
        data = cache_file.read_bytes()
        return None if data == b"__404__" else data
    for attempt in range(attempts):
        wait = MIN_INTERVAL - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(data)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_bytes(b"__404__")
                return None
            if e.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
        except urllib.error.URLError:
            if attempt == attempts - 1:
                raise
        time.sleep(2 ** attempt)
    return None


def search(max_pages: int | None = None) -> list[dict]:
    results, cursor, page = [], "*", 0
    while True:
        params = {"query": QUERY, "format": "json", "resultType": "core", "pageSize": 100, "cursorMark": cursor}
        url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
        key = hashlib.sha1(url.encode()).hexdigest()[:16]
        data = json.loads(_get(url, CACHE / "search" / f"{key}.json"))
        hits = data.get("resultList", {}).get("result", [])
        results += hits
        page += 1
        nxt = data.get("nextCursorMark")
        if not hits or not nxt or nxt == cursor or (max_pages and page >= max_pages):
            return results
        cursor = nxt


def _record(hit: dict) -> dict:
    journal = ((hit.get("journalInfo") or {}).get("journal") or {}).get("title") or hit.get("journalTitle") or ""
    return {"pmcid": hit.get("pmcid"), "pmid": hit.get("pmid"), "doi": hit.get("doi"), "title": hit.get("title"),
            "authors": hit.get("authorString") or "", "journal": journal, "year": hit.get("pubYear"),
            "license": normalise_license(hit.get("license")), "license_ok": license_allowed(hit.get("license"))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-pages", type=int, default=None)
    a = ap.parse_args()
    hits = search(a.max_pages)
    seen, records = set(), []
    for h in hits:
        key = h.get("pmcid") or h.get("id")
        if key in seen:
            continue
        seen.add(key)
        records.append(_record(h))
    for r in records:
        r["fulltext"] = False
        if r["license_ok"] and r["pmcid"]:
            xml = _get(FULLTEXT_URL.format(pmcid=r["pmcid"]), CACHE / "xml" / f"{r['pmcid']}.xml")
            r["fulltext"] = xml is not None
    (CACHE / "articles.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
    by_license: dict[str, int] = {}
    for r in records:
        by_license[r["license"] or "(none)"] = by_license.get(r["license"] or "(none)", 0) + 1
    print(json.dumps({"articles": len(records), "license_ok": sum(r["license_ok"] for r in records),
                      "with_fulltext": sum(r["fulltext"] for r in records), "by_license": by_license}, indent=1))


if __name__ == "__main__":
    main()
