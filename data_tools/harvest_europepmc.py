r"""
Harvest open-access LI-RADS articles from Europe PMC.

    .\.venv\Scripts\python.exe data_tools\harvest_europepmc.py [--max-pages N]

Uses the public Europe PMC REST API (no key). Runs the three queries below, deduplicates by
PMCID, keeps only articles whose license allows research use (CC0, CC BY, CC BY-NC, CC BY-SA,
CC BY-NC-SA; no-derivatives licenses are excluded) and downloads their full-text JATS XML.
At most three requests per second across all workers, retries with exponential backoff, and every
response is cached under data\raw\europepmc\ (git-ignored), so a re-run resumes where it stopped.

Output: data\raw\europepmc\articles.json (one record per article: license, filter result, which
queries found it, full text yes/no) and data\raw\europepmc\query_counts.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "europepmc"
SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
QUERIES = {
    "q1_case_reports": '("LI-RADS" OR "LIRADS") AND ("case report" OR "case presentation") AND OPEN_ACCESS:y',
    "q2_categories": '("LI-RADS" OR "LIRADS") AND ("LR-5" OR "LR-4" OR "LR-3" OR "LR-M" OR "LI-RADS 5" OR '
                     '"LI-RADS 4" OR "LI-RADS 3") AND (MRI OR CT) AND OPEN_ACCESS:y',
    "q3_features": '"hepatocellular carcinoma" AND "LI-RADS" AND ("arterial phase hyperenhancement" OR "washout") '
                   'AND OPEN_ACCESS:y',
}
QUERY = QUERIES["q1_case_reports"]
ALLOWED_LICENSES = {"cc0", "cc by", "cc by-nc", "cc by-sa", "cc by-nc-sa"}
USER_AGENT = "rads-envelope-data-tools/1.0 (research prototype)"
MIN_INTERVAL = 1 / 3            # at most 3 requests per second, shared by all workers
WORKERS = 3
_last_request = [0.0]
_rate_lock = threading.Lock()


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
        with _rate_lock:                                   # global limit across worker threads
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


def search(max_pages: int | None = None, query: str = QUERY) -> list[dict]:
    results, cursor, page = [], "*", 0
    while True:
        params = {"query": query, "format": "json", "resultType": "core", "pageSize": 100, "cursorMark": cursor}
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


def _fetch_fulltext(r: dict) -> None:
    path = CACHE / "xml" / f"{r['pmcid']}.xml"
    try:
        r["fulltext"] = _get(FULLTEXT_URL.format(pmcid=r["pmcid"]), path) is not None
    except Exception as e:                                  # keep going; reported in the summary
        r["fulltext"], r["fulltext_error"] = False, f"{type(e).__name__}: {e}"
    if r["fulltext"]:
        r["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-pages", type=int, default=None)
    a = ap.parse_args()
    records: dict[str, dict] = {}
    counts = {}
    for qid, query in QUERIES.items():
        hits = search(a.max_pages, query)
        ids = set()
        for h in hits:
            key = h.get("pmcid") or h.get("id")
            ids.add(key)
            rec = records.setdefault(key, {**_record(h), "queries": []})
            rec["queries"].append(qid)
        counts[qid] = {"query": query, "hits": len(hits), "unique": len(ids),
                       "license_ok": sum(records[k]["license_ok"] for k in ids)}
    todo = [r for r in records.values() if r["license_ok"] and r["pmcid"]]
    for r in records.values():
        r.setdefault("fulltext", False)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(_fetch_fulltext, todo))
    out = list(records.values())
    (CACHE / "articles.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for qid in counts:
        counts[qid]["with_fulltext"] = sum(r["fulltext"] for r in out if qid in r["queries"])
    by_license: dict[str, int] = {}
    for r in out:
        by_license[r["license"] or "(none)"] = by_license.get(r["license"] or "(none)", 0) + 1
    summary = {"articles_unique": len(out), "license_ok": sum(r["license_ok"] for r in out),
               "with_fulltext": sum(r["fulltext"] for r in out),
               "fulltext_errors": sum("fulltext_error" in r for r in out), "by_license": by_license, "queries": counts}
    (CACHE / "query_counts.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
