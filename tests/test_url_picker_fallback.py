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
    result = run_parse_url_pick_with_content(
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
        '{"url":"https://www.amaris-b.com/","reason":"official website"}',
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://www.amaris-b.com/"
    assert result["canonical_domain"] == "amaris-b.com"


def test_url_picker_fallback_picks_acronym_domain_from_snippet():
    result = run_parse_url_pick_with_content(
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
        '{"url":"https://www.aamg.co","reason":"official website found in result snippet"}',
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


def test_url_picker_accepts_official_hosted_page_when_llm_selects_it():
    result = run_parse_url_pick_with_content(
        "Appletree Medical",
        [
            {
                "title": "Appletree Medical - Family medicine and Occupational Health",
                "url": "https://appletreemedicalsingapore.wordpress.com/",
                "snippet": "Contact us at Blk 416 Ang Mo Kio Avenue 10 Singapore.",
            }
        ],
        '{"url":"https://appletreemedicalsingapore.wordpress.com/","reason":"official hosted page with Singapore contact details"}',
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://appletreemedicalsingapore.wordpress.com/"


def test_url_picker_accepts_close_official_name_variant_when_llm_selects_it():
    result = run_parse_url_pick_with_content(
        "Arise",
        [
            {
                "title": "Arise Services Pte Ltd: Home",
                "url": "https://arise.com.sg/",
                "snippet": "Preferred provider for food hygiene and first aid courses in Singapore.",
            }
        ],
        '{"url":"https://arise.com.sg/","reason":"official site uses close legal name variant"}',
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://arise.com.sg/"


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


def test_url_picker_falls_back_when_llm_selects_directory_listing():
    result = run_parse_url_pick_with_content(
        "HL Family Clinic & Surgery",
        [
            {
                "rank": 1,
                "title": "HL Family Clinic & Surgery - Yelp",
                "url": "https://www.yelp.com/biz/hl-family-clinic-and-surgery-singapore-2",
                "snippet": "Directory listing for HL Family Clinic & Surgery.",
            },
            {
                "rank": 2,
                "title": "HL Family Clinic & Surgery",
                "url": "https://hlfamilyclinic.com.sg/",
                "snippet": "Official website of HL Family Clinic & Surgery in Singapore.",
            },
        ],
        '{"url":"https://www.yelp.com/biz/hl-family-clinic-and-surgery-singapore-2","reason":"top result"}',
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://hlfamilyclinic.com.sg/"
    evidence = json.loads(result["search_evidence_json"])
    assert evidence["llm_picked_url"].startswith("https://www.yelp.com/")
    assert evidence["fallback_url"] == "https://hlfamilyclinic.com.sg/"


def test_url_picker_rejects_shortener_even_when_llm_selects_it():
    result = run_parse_url_pick_with_content(
        "Toh Yi Family Clinic",
        [
            {
                "rank": 1,
                "title": "Toh Yi Family Clinic",
                "url": "https://bit.ly/tohyi",
                "snippet": "Short link for Toh Yi Family Clinic.",
            }
        ],
        '{"url":"https://bit.ly/tohyi","reason":"top result"}',
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_rejects_marketplace_product_page_even_when_named():
    result = run_parse_url_pick_with_content(
        "Praventac - Acne Treatment",
        [
            {
                "rank": 1,
                "title": "PRAVENTAC Natural Acne Treatment Supplement",
                "url": "https://www.amazon.sg/PRAVENTAC-Natural-Blemishes-Supplement-60Capsules/dp/B01NBQ1V0A",
                "snippet": "Praventac acne treatment product page on Amazon Singapore.",
            }
        ],
        '{"url":"https://www.amazon.sg/PRAVENTAC-Natural-Blemishes-Supplement-60Capsules/dp/B01NBQ1V0A","reason":"brand and product match"}',
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_rejects_nlb_directory_result():
    result = run_parse_url_pick_with_content(
        "Bishan Grace Clinic",
        [
            {
                "rank": 1,
                "title": "Bishan Grace Clinic - Singapore Infopedia",
                "url": "https://eresources.nlb.gov.sg/webarchives/details/www.bishangraceclinic.example",
                "snippet": "Archived directory information for Bishan Grace Clinic.",
            }
        ],
        '{"url":"https://eresources.nlb.gov.sg/webarchives/details/www.bishangraceclinic.example","reason":"has clinic name"}',
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_rejects_practo_directory_result():
    result = run_parse_url_pick_with_content(
        "HL Family Clinic & Surgery",
        [
            {
                "rank": 1,
                "title": "HL Family Clinic & Surgery - Practo",
                "url": "https://www.practo.com/singapore/clinic/hl-family-clinic-and-surgery",
                "snippet": "Practo listing for HL Family Clinic & Surgery.",
            }
        ],
        '{"url":"https://www.practo.com/singapore/clinic/hl-family-clinic-and-surgery","reason":"has clinic name"}',
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_rejects_company_directory_result():
    result = run_parse_url_pick_with_content(
        "HL Family Clinic & Surgery",
        [
            {
                "rank": 1,
                "title": "HL Family Clinic & Surgery Pte Ltd",
                "url": "https://sg.ltddir.com/companies/hl-family-clinic-surgery-pte-ltd/",
                "snippet": "Company directory listing for HL Family Clinic & Surgery Pte Ltd.",
            }
        ],
        '{"url":"https://sg.ltddir.com/companies/hl-family-clinic-surgery-pte-ltd/","reason":"has company name"}',
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_rejects_doc_sg_directory_result():
    result = run_parse_url_pick_with_content(
        "The Medical Centre Clinic (Hong Leong)",
        [
            {
                "rank": 1,
                "title": "the medical centre clinic (hong leong) - Singapore - doc.sg",
                "url": "https://doc.sg/clinic/the-medical-centre-clinic-hong-leong/",
                "snippet": "Directory profile for The Medical Centre Clinic Hong Leong.",
            }
        ],
        '{"url":"https://doc.sg/clinic/the-medical-centre-clinic-hong-leong/","reason":"has clinic name"}',
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_rejects_contact_page_landing_result():
    result = run_parse_url_pick_with_content(
        "Toh Yi Family Clinic",
        [
            {
                "rank": 1,
                "title": "Toh Yi Family Clinic",
                "url": "https://sg64366-toh-yi-family-clinic.contact.page/",
                "snippet": "Landing page for Toh Yi Family Clinic.",
            }
        ],
        '{"url":"https://sg64366-toh-yi-family-clinic.contact.page/","reason":"has clinic name"}',
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_rejects_path_only_identity_on_third_party_listing():
    result = run_parse_url_pick(
        "Mao Medical Centre & Surgery",
        [
            {
                "rank": 1,
                "title": "Mao Medical Centre & Surgery Pte. Ltd. - ThreeBestRated.sg",
                "url": "https://threebestrated.sg/hospitals/mao-medical-centre-and-surgery-pte.-ltd.-bukit-merah-211116734",
                "snippet": "Mao Medical Centre & Surgery Pte. Ltd. · Bukit Merah · 62781910.",
            },
            {
                "rank": 2,
                "title": "Mao Medical Centre & Surgery - Practo",
                "url": "https://www.practo.com/singapore/clinic/mao-medical-centre-surgery-outram",
                "snippet": "Address and timings for Mao Medical Centre & Surgery.",
            },
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_accepts_bridgepoint_core_domain_without_branch_tokens():
    result = run_parse_url_pick_with_content(
        "Bridgepoint Health (Jalan Bukit Merah Clinic)",
        [
            {
                "rank": 1,
                "title": "Bridgepoint Health",
                "url": "https://bridgepointhealth.sg/",
                "snippet": "Ang is an accredited Family Physician and Clinic Lead at Bridgepoint Health.",
            },
            {
                "rank": 2,
                "title": "Bridgepoint Health (@bridgepointhealthsg) - Facebook",
                "url": "https://www.facebook.com/bridgepointhealthsg/",
                "snippet": "BH Jalan Bukit Merah clinic is at Tiong Bahru Orchid.",
            },
        ],
        '{"url":"https://bridgepointhealth.sg/","reason":"official Bridgepoint Health site"}',
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://bridgepointhealth.sg/"


def test_url_picker_keeps_best_matching_subpage_but_sets_root_for_scrape():
    result = run_parse_url_pick_with_content(
        "P J Clinic",
        [
            {
                "rank": 1,
                "title": "Appointments - PJ Clinic",
                "url": "https://www.pjclinic.org/appointments",
                "snippet": "Official website of PJ Clinic. Book appointments for the Jalan Bukit Merah clinic.",
            },
            {
                "rank": 2,
                "title": "PJ Clinic",
                "url": "https://www.pjclinic.org/",
                "snippet": "Official website of PJ Clinic.",
            },
        ],
        '{"url":"https://www.pjclinic.org/appointments","reason":"best matching official subpage"}',
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://www.pjclinic.org/appointments"
    assert result["homepage_root_url"] == "https://www.pjclinic.org/"
    evidence = json.loads(result["search_evidence_json"])
    assert evidence["operating_root_url"] == "https://www.pjclinic.org/"


def test_url_picker_prefers_normal_official_domain_over_hosted_landing_page():
    result = run_parse_url_pick_with_content(
        "Cavenagh Medical Clinic and Home Care",
        [
            {
                "rank": 1,
                "title": "Healthier SG with Cavenagh Medical",
                "url": "https://cavenaghmedical.page/hsg",
                "snippet": "Specializing in tailored healthcare and complex home care.",
            },
            {
                "rank": 3,
                "title": "Cavenagh Medical Clinic and Home Care | LinkedIn",
                "url": "https://sg.linkedin.com/company/cavenaghmedical",
                "snippet": "A modern primary care clinic that also supports home-based medical services. https://cavenaghmedical.com/",
            },
        ],
        '{"url":"https://cavenaghmedical.page/hsg","reason":"hosted official page"}',
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://cavenaghmedical.com/"
    assert result["homepage_root_url"] == "https://cavenaghmedical.com/"
    evidence = json.loads(result["search_evidence_json"])
    assert evidence["normalized_from_hosted_url"] == "https://cavenaghmedical.page/hsg"


def test_url_picker_accepts_spaced_initial_company_when_official_result_says_so():
    result = run_parse_url_pick_with_content(
        "P J Clinic",
        [
            {
                "rank": 1,
                "title": "Dr Tan Poh Kiang | PJ Clinic | Singapore",
                "url": "https://www.pjclinic.org/",
                "snippet": "Official website of PJ Clinic · Blk 11 Jalan Bukit Merah.",
            },
            {
                "rank": 2,
                "title": "Appointments - PJ Clinic",
                "url": "https://www.pjclinic.org/appointments",
                "snippet": "Our clinic address and email.",
            },
        ],
        '{"url":"https://www.pjclinic.org/","reason":"official website of PJ Clinic"}',
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://www.pjclinic.org/"


def test_url_picker_uses_serper_fallback_when_llm_returns_blank_but_official_result_exists():
    result = run_parse_url_pick_with_content(
        "The Clinic Group @ Marina One",
        [
            {
                "rank": 1,
                "title": "The Clinic Group @ Marina One - Singapore - Healthway Medical",
                "url": "https://healthwaymedical.com/clinics/the-clinic-group-marina-one",
                "snippet": "The Clinic Group @ Marina One is a family clinic.",
            },
            {
                "rank": 2,
                "title": "The Clinic Group: Affordable Checkup Clinic in Singapore",
                "url": "https://theclinicgroup.com.sg/",
                "snippet": "Get Directions; The Clinic Group @ Marina One. 5 Straits View, #B2-54, Marina One.",
            },
        ],
        '{"url":"","reason":"none clear"}',
    )

    assert result["status"] == "url_picked"
    assert result["url_picked"] == "https://theclinicgroup.com.sg/"
    evidence = json.loads(result["search_evidence_json"])
    assert evidence["fallback_url"] == "https://theclinicgroup.com.sg/"


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


def test_url_picker_fallback_rejects_third_party_company_slug():
    result = run_parse_url_pick(
        "Ann Arbor Dental Surgery",
        [
            {
                "title": "Ann Arbor Dental Surgery",
                "url": "https://www.tampinesmart.com/ann-arbor-dental-surgery",
                "snippet": "Ann Arbor Dental Surgery is located at Tampines Mart.",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_fallback_rejects_public_webmail_domain():
    result = run_parse_url_pick(
        "Anchor Health Family Clinic",
        [
            {
                "title": "Anchor Health Family Clinic",
                "url": "https://gmail.com",
                "snippet": "Contact Anchor Health Family Clinic at anchorhealth@gmail.com",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_picker_fallback_does_not_promote_listing_title_domain():
    result = run_parse_url_pick(
        "Ann Arbor Dental Surgery",
        [
            {
                "title": "ann arbor dental surgery - Singapore - doc.sg",
                "url": "https://doc.sg/clinic/ann-arbor-dental-surgery/",
                "snippet": "Contact Details at Tampines Mart Singapore.",
            }
        ],
    )

    assert result["status"] == "skipped"
    assert result["url_picked"] == ""


def test_url_discovery_requests_ten_serper_results():
    workflow = json.loads((ROOT / "wf-worker.json").read_text(encoding="utf-8"))
    node = next(entry for entry in workflow["nodes"] if entry["name"] == "Build URL Discovery Query")
    assert "num: 10" in node["parameters"]["jsCode"]


def test_url_discovery_query_strips_parenthetical_branch_noise():
    workflow = json.loads((ROOT / "wf-worker.json").read_text(encoding="utf-8"))
    node = next(entry for entry in workflow["nodes"] if entry["name"] == "Build URL Discovery Query")
    script = f"""
const nodeCode = {json.dumps(node["parameters"]["jsCode"])};
const $json = {{ company_name: "Bridgepoint Health (Jalan Bukit Merah Clinic)" }};
const result = new Function('$json', nodeCode)($json);
console.log(JSON.stringify(result.json));
"""
    output = subprocess.check_output(["node", "-e", script], text=True)
    result = json.loads(output)

    assert result["serper_query"] == "Bridgepoint Health Singapore"


def test_url_picker_prompt_requires_blank_when_unclear():
    workflow = json.loads((ROOT / "wf-worker.json").read_text(encoding="utf-8"))
    node = next(entry for entry in workflow["nodes"] if entry["name"] == "Prepare URL Discovery Pick")
    prompt_code = node["parameters"]["jsCode"]

    assert "Return blank unless the result is clearly" in prompt_code
    assert "Do not guess" in prompt_code
    assert "Accept close official-name variants" in prompt_code
    assert "Accept a hosted official site such as WordPress" in prompt_code
    assert "Prefer a normal company-owned domain over hosted landing pages" in prompt_code


def test_url_picker_prompt_node_compiles():
    workflow = json.loads((ROOT / "wf-worker.json").read_text(encoding="utf-8"))
    node = next(entry for entry in workflow["nodes"] if entry["name"] == "Prepare URL Discovery Pick")
    script = f"""
const nodeCode = {json.dumps(node["parameters"]["jsCode"])};
new Function('$', 'node', nodeCode);
"""
    subprocess.check_call(["node", "-e", script])


def test_url_pick_patch_clears_homepage_root_on_skip():
    workflow = json.loads((ROOT / "wf-worker.json").read_text(encoding="utf-8"))
    parse_node = next(entry for entry in workflow["nodes"] if entry["name"] == "Parse URL Pick")
    patch_node = next(entry for entry in workflow["nodes"] if entry["name"] == "Patch URL Picked")

    assert "homepage_root_url: operatingRootUrl" in parse_node["parameters"]["jsCode"]
    assert "homepage_root_url: $json.homepage_root_url" in patch_node["parameters"]["jsonBody"]


def test_dedupe_never_skips_lower_id_for_higher_id_match():
    workflow = json.loads((ROOT / "wf-worker.json").read_text(encoding="utf-8"))
    node = next(entry for entry in workflow["nodes"] if entry["name"] == "Apply Dedupe Result")
    code = node["parameters"]["jsCode"]

    assert "Number(row.Id) < Number(picked.Id)" in code
    assert "Number(row.Id) !== Number(picked.Id)" not in code
