import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_parse_url_pick(company_name, results):
    return run_parse_url_pick_with_content(company_name, results, '{"url":"","reason":"none clear"}')


def run_parse_url_pick_with_content(company_name, results, content):
    script = f"""
const fs = require('fs');
const workflow = JSON.parse(fs.readFileSync({json.dumps(str(ROOT / "wf-worker.json"))}, 'utf8'));
const node = workflow.nodes.find((entry) => entry.name === 'Parse URL Pick');
const prepared = {{
  Id: 1,
  company_name: {json.dumps(company_name)},
  serper_query: {json.dumps(company_name + " Singapore")},
  serper_results: {json.dumps(results)},
  serper_error: '',
}};
function $(name) {{
  if (name === 'Prepare URL Discovery Pick') return {{ all: () => [{{ json: prepared }}] }};
  return {{ all: () => [] }};
}}
const $json = {{ choices: [{{ message: {{ content: {json.dumps(content)} }} }}] }};
const result = new Function('$', '$json', '$itemIndex', node.parameters.jsCode)($, $json, 0);
console.log(JSON.stringify(result.json));
"""
    output = subprocess.check_output(["node", "-e", script], text=True)
    return json.loads(output)


def test_url_picker_fallback_picks_root_homepage():
    result = run_parse_url_pick(
        "Amaris B. Clinic",
        [
            {
                "title": "Amaris B. Clinic Singapore | Aesthetics, Sculpting, Fitness",
                "url": "https://www.amaris-b.com/",
                "snippet": "Welcome to Amaris B. Clinic.",
            },
            {
                "title": "Amaris B. Clinic | The Best Singapore",
                "url": "https://www.thebestsingapore.com/biz-review/amaris-b-clinic-review/",
                "snippet": "Review listing.",
            },
        ],
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://www.amaris-b.com/"
    assert result["canonical_domain"] == "amaris-b.com"


def test_url_picker_fallback_picks_acronym_domain_from_snippet():
    result = run_parse_url_pick(
        "ASIAN AMERICAN MEDICAL GROUP",
        [
            {
                "title": "Asian American Medical Group | Singapore",
                "url": "https://www.bizapore.com/en/asian-american-medical-group-6476-2088",
                "snippet": "The website for Asian American Medical Group is www.aamg.co.",
            },
            {
                "title": "ASIAN AMERICAN MEDICAL GROUP | LinkedIn",
                "url": "https://sg.linkedin.com/company/asian-american-medical-group-limited",
                "snippet": "Company profile.",
            },
        ],
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://www.aamg.co"
    assert result["canonical_domain"] == "aamg.co"


def test_url_picker_fallback_keeps_unclear_results_skipped():
    result = run_parse_url_pick(
        "Anchor Health Family Clinic",
        [
            {
                "title": "Anchor Health Family Clinic | Reviews",
                "url": "https://wherecrowded.sg/at/place/anchor-health-family-clinic",
                "snippet": "Browse doctors and clinics.",
            },
            {
                "title": "Participating Clinics PDF",
                "url": "https://example.gov.sg/clinics.pdf",
                "snippet": "Anchor Health Family Clinic address.",
            },
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_rejects_weak_llm_acronym_pick():
    result = run_parse_url_pick_with_content(
        "ASIAN AMERICAN MEDICAL GROUP",
        [
            {
                "rank": 8,
                "title": "AAMG Doctors",
                "url": "https://aamgdoctors.net/",
                "snippet": "Welcome! Please select your preferred language.",
            }
        ],
        '{"url":"https://aamgdoctors.net/","reason":"looks official"}',
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""
    evidence = json.loads(result["search_evidence_json"])
    assert evidence["llm_picked_url"] == "https://aamgdoctors.net/"
    assert "rejected" in evidence["reason"]


def test_url_picker_fallback_rejects_news_article():
    result = run_parse_url_pick(
        "ASIAN AMERICAN MEDICAL GROUP",
        [
            {
                "title": "Singapore-based Asian American Medical Group breaks ground on ...",
                "url": "https://healthcareasiamagazine.com/healthcare/feature/singapore-based-asian-american-medical-group-breaks-ground-life-science-park-in-c",
                "snippet": "Singapore-based Asian American Medical Group broke ground on a life science park.",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_fallback_rejects_provider_listing_path():
    result = run_parse_url_pick(
        "ASIAN AMERICAN MEDICAL GROUP",
        [
            {
                "title": "Asian American Medical Group AAMG",
                "url": "https://kakilist.com/provider/asian-american-medical-group-aamg-19669",
                "snippet": "Provider listing for Asian American Medical Group.",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_fallback_rejects_stock_profile_path():
    result = run_parse_url_pick(
        "ASIAN AMERICAN MEDICAL GROUP",
        [
            {
                "title": "Asian American Medical Group Company Profile",
                "url": "https://www.itiger.com/stock/AJJ.AU/company",
                "snippet": "Asian American Medical Group Limited provides medical services in Singapore.",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_fallback_rejects_market_profile_path():
    result = run_parse_url_pick(
        "ASIAN AMERICAN MEDICAL GROUP",
        [
            {
                "title": "Asian American Medical Group Limited",
                "url": "https://www.listcorp.com/asx/ajj/asian-american-medical-group-limited",
                "snippet": "Asian American Medical Group operates a leading liver transplant centre in Singapore.",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_fallback_ignores_decimal_numbers():
    result = run_parse_url_pick(
        "ASIAN AMERICAN MEDICAL GROUP",
        [
            {
                "title": "Asian American Medical Group Limited",
                "url": "https://www.listcorp.com/asx/ajj/asian-american-medical-group-limited",
                "snippet": "Market cap 1.3076616326114 and Singapore healthcare profile.",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_fallback_rejects_partial_token_match():
    result = run_parse_url_pick(
        "ASIAN AMERICAN MEDICAL GROUP",
        [
            {
                "title": "Asian Healthcare Contact Us",
                "url": "https://asianhealthcare.com.sg/contact-us/",
                "snippet": "Asian Healthcare clinic contact page in Singapore.",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_fallback_rejects_profile_slug():
    result = run_parse_url_pick(
        "ASIAN AMERICAN MEDICAL GROUP",
        [
            {
                "title": "ASIAN AMERICAN MEDICAL GROUP Information",
                "url": "https://rocketreach.co/asian-american-medical-group-profile_b4478287fac823d6",
                "snippet": "ASIAN AMERICAN MEDICAL GROUP is located in Singapore.",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_discovery_requests_twenty_serper_results():
    workflow = json.loads((ROOT / "wf-worker.json").read_text(encoding="utf-8"))
    node = next(entry for entry in workflow["nodes"] if entry["name"] == "Build URL Discovery Query")
    assert "num: 20" in node["parameters"]["jsCode"]


def test_url_pick_patch_clears_homepage_root_on_skip():
    workflow = json.loads((ROOT / "wf-worker.json").read_text(encoding="utf-8"))
    parse_node = next(entry for entry in workflow["nodes"] if entry["name"] == "Parse URL Pick")
    patch_node = next(entry for entry in workflow["nodes"] if entry["name"] == "Patch URL Picked")

    assert "homepage_root_url: pickedUrl" in parse_node["parameters"]["jsCode"]
    assert "homepage_root_url: $json.homepage_root_url" in patch_node["parameters"]["jsonBody"]
