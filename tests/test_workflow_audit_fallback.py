import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_collect_node(item):
    script = f"""
const fs = require('fs');
const workflow = JSON.parse(fs.readFileSync('{ROOT / "wf-cold-email-planner.json"}', 'utf8'));
const node = workflow.nodes.find((entry) => entry.name === 'Collect NocoDB Patches');
const items = [{json.dumps({"json": item})}];
const result = new Function('items', node.parameters.jsCode)(items);
console.log(JSON.stringify(result[0].json));
"""
    output = subprocess.check_output(["node", "-e", script], text=True)
    return json.loads(output)


def test_n8n_funding_fallback_uses_company_team_greeting_and_no_duplicate_caveat():
    claim = "The relevant route appears worth checking, subject to programme confirmation."
    result = run_collect_node(
        {
            "patch": {
                "Id": 273,
                "company_name": "Amaris B. Clinic",
                "pressure_type": "hia_regulatory",
                "funding_claim_line": claim,
                "email_3_body": "Funding email missing the exact claim.",
                "email_sequence_json": json.dumps({"email_3": {"body": "", "word_count": 0}}),
                "email_quality_flags": json.dumps(["email_3_missing_funding_claim_line"]),
            }
        }
    )

    patch = result["patches"][0]
    sequence = json.loads(patch["email_sequence_json"])
    assert patch["email_3_body"].startswith("Hi Amaris B. Clinic team,")
    assert not patch["email_3_body"].startswith("Hi,")
    assert patch["email_3_body"].count("subject to programme confirmation") == 1
    assert sequence["email_3"]["body"] == patch["email_3_body"]
    assert sequence["email_3"]["word_count"] > 0


def test_n8n_funding_fallback_uses_team_greeting_without_company_name():
    result = run_collect_node(
        {
            "patch": {
                "Id": 999,
                "pressure_type": "pdpa_safeguards",
                "funding_claim_line": "Funding route needs human review before use.",
                "email_3_body": "",
                "email_sequence_json": json.dumps({"email_3": {"body": "", "word_count": 0}}),
                "email_quality_flags": "[]",
            }
        }
    )

    assert result["patches"][0]["email_3_body"].startswith("Hi team,")


def test_n8n_audit_includes_subjects_and_email_four_body():
    result = run_collect_node(
        {
            "patch": {
                "Id": 274,
                "company_name": "Amazing Hearing Group",
                "pressure_type": "hia_regulatory",
                "hia_service_type_guess": "hearing_care",
                "hia_timeline_batch_guess": "unknown",
                "funding_status": "verified_match",
                "email_quality_flags": "[]",
                "email_1_subject": "HIA readiness",
                "email_1_body": "One",
                "email_2_subject": "Re: HIA readiness",
                "email_2_body": "Two",
                "email_3_subject": "HIA / cyber funding",
                "email_3_body": "Three",
                "email_4_subject": "close the loop?",
                "email_4_body": "Four",
            }
        }
    )

    audit = result["audits"][0]
    assert audit["email_1_subject"] == "HIA readiness"
    assert audit["email_4_subject"] == "close the loop?"
    assert audit["email_4_body"] == "Four"
