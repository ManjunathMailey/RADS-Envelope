"""Landing page routes and data endpoints."""
import csv
import json
from pathlib import Path

from fastapi.testclient import TestClient

from radsenvelope.api import app as appmod

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(appmod.app)


def test_routes_serve_landing_and_app():
    landing = client.get("/")
    assert landing.status_code == 200 and "LI-RADS reports that never contradict the rules" in landing.text
    assert 'href="/app"' in landing.text and "/app?example=1" in landing.text
    app = client.get("/app")
    assert app.status_code == 200 and 'id="report"' in app.text           # the analyser, unchanged
    for asset in ("/static/landing.css", "/static/landing.js", "/static/app.js", "/static/app.css"):
        assert client.get(asset).status_code == 200


def test_headline_numbers_come_from_result_files():
    h = client.get("/api/headline").json()["b1_contradiction"]
    res = json.loads((ROOT / "data" / "benchmark" / "results_comparison.json").read_text(encoding="utf-8"))
    rate = res["systems"]["B1"]["summary"]["contradiction_rate"]
    assert (h["robustness"]["k"], h["robustness"]["n"], h["robustness"]["value"]) == (rate["k"], rate["n"], rate["value"])
    assert h["robustness"]["label"] == "robustness test (rule-generated gold)"


def test_landing_page_has_no_hard_coded_result_numbers():
    html = (ROOT / "web" / "landing.html").read_text(encoding="utf-8")
    assert "%" not in html.split('id="problemNumber"')[1].split("</li>")[0]


def test_font_is_self_hosted_and_pages_make_no_external_requests():
    font = client.get("/static/fonts/InterVariable.woff2")
    assert font.status_code == 200 and font.content[:4] == b"wOF2"
    assert "InterVariable.woff2" in client.get("/static/app.css").text
    for page in ("/", "/app"):
        html = client.get(page).text
        assert "googleapis" not in html and "gstatic" not in html
    assert (ROOT / "web" / "static" / "fonts" / "OFL-Inter.txt").exists()


def test_example_is_a_development_case():
    x = client.get("/api/example").json()
    assert x["id"] == appmod.EXAMPLE_CASE and x["report"] and x["license"]
    split_file = ROOT / "data" / "real" / "split.csv"
    if split_file.exists():
        split = {r["id"]: r["split"] for r in csv.DictReader(open(split_file, encoding="utf-8"))}
        assert split[x["id"]] == "dev"                                    # never a held-out test case


def test_headline_reports_rule_contradictions_from_result_files():
    h = client.get("/api/headline").json()["rule_contradiction"]
    res = json.loads((ROOT / "data" / "benchmark" / "results_comparison.json").read_text(encoding="utf-8"))
    rate = res["systems"]["OursC"]["summary"]["contradiction_rate"]
    assert (h["robustness"]["k"], h["robustness"]["n"]) == (rate["k"], rate["n"])


def test_landing_demo_is_computed_by_the_engine():
    import importlib.util
    spec = importlib.util.spec_from_file_location("landing_demo", ROOT / "data_tools" / "landing_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stored = json.loads((ROOT / "web" / "static" / "landing_demo.json").read_text(encoding="utf-8"))
    assert stored == json.loads(json.dumps(mod.build(), ensure_ascii=False))       # regenerate with data_tools/landing_demo.py
    assert len(stored["documented"]["envelope"]) > 1 and stored["documented"]["decision_critical"]
    assert all(len(a["envelope"]) == 1 for a in stored["answers"].values())        # one answer settles it


def test_brand_assets_are_served():
    for path in ("/static/brand/favicon.svg", "/static/brand/favicon-32.png", "/static/brand/og.png", "/static/landing_demo.json"):
        assert client.get(path).status_code == 200
    html = client.get("/").text
    assert 'property="og:image"' in html and "favicon.svg" in html


def test_headline_pools_real_cases_from_dev_and_test_files():
    h = client.get("/api/headline").json()
    for system, key in (("B1", "b1_contradiction"), ("OursC", "rule_contradiction")):
        k = n = 0
        for split in ("dev", "test"):
            res = json.loads((ROOT / "data" / "real" / f"results.comparison.{split}.json").read_text(encoding="utf-8"))
            rate = res["systems"][system]["summary"]["contradiction_rate"]
            k, n = k + rate["k"], n + rate["n"]
        assert (h[key]["real_all"]["k"], h[key]["real_all"]["n"]) == (k, n)
