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
