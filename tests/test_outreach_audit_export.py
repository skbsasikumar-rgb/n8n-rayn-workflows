import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "export_outreach_audit_markdown.py"
spec = importlib.util.spec_from_file_location("export_outreach_audit_markdown", MODULE_PATH)
exporter = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(exporter)


def test_export_outreach_audit_markdown_full_sequence():
    markdown = exporter.render_markdown(
        [
            {
                "row_id": 273,
                "company_name": "Amaris B. Clinic",
                "pressure_type": "hia_regulatory",
                "hia_service_type_guess": "diagnostic",
                "hia_timeline_batch_guess": "Batch 1 - Sep 2027",
                "funding_status": "verified_match",
                "email_quality_flags": ["funding_needs_review"],
                "email_1_subject": "HIA readiness",
                "email_1_body": "Email one body.",
                "email_2_subject": "Re: HIA readiness",
                "email_2_body": "Email two body.",
                "email_3_subject": "HIA / cyber funding",
                "email_3_body": "Email three body.",
                "email_4_subject": "close the loop?",
                "email_4_body": "Email four body.",
            }
        ]
    )

    assert "## 273 - Amaris B. Clinic" in markdown
    assert "- pressure_type: `hia_regulatory`" in markdown
    assert "funding_needs_review" in markdown
    assert "### Email 1: HIA readiness" in markdown
    assert "### Email 4: close the loop?" in markdown
    assert "Email four body." in markdown
