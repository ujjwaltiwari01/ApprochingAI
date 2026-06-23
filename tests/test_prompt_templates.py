"""Ensure prompt templates format without KeyError."""

"""Tests: prompt templates must format without KeyError — guards against {brace} bugs in prompts."""
from pathlib import Path

from src.services.email_generator import EmailGenerator


def _dummy_kwargs():
    return {
        "company_name": "Test Agency",
        "agency_analysis": '{"summary": "digital marketing agency"}',
        "sender_profile": '{"name": "Ujjwal"}',
        "portfolio_url": "https://example.com/portfolio",
        "linkedin_url": "https://linkedin.com/in/test",
        "recipient_greeting_instruction": "No recipient first name available.",
        "followup_number": 1,
        "previous_subject": "test subject",
        "engagement_type": "opened_no_reply",
        "resume_line": "",
    }


def test_all_prompt_templates_format():
    gen = EmailGenerator()
    kwargs = _dummy_kwargs()
    prompts_dir = Path(__file__).parent.parent / "prompts"

    gen._format_prompt(
        (prompts_dir / "master_email.txt").read_text(encoding="utf-8"),
        **{k: kwargs[k] for k in (
            "portfolio_url", "linkedin_url", "sender_profile",
            "agency_analysis", "company_name", "recipient_greeting_instruction",
        )},
    )
    gen._format_prompt(
        (prompts_dir / "subject_lines.txt").read_text(encoding="utf-8"),
        company_name=kwargs["company_name"],
        agency_analysis=kwargs["agency_analysis"],
    )
    gen._format_prompt(
        (prompts_dir / "followup_templates.txt").read_text(encoding="utf-8"),
        **{k: kwargs[k] for k in (
            "company_name", "followup_number", "previous_subject",
            "engagement_type", "portfolio_url", "linkedin_url",
            "resume_line", "agency_analysis", "recipient_greeting_instruction",
        )},
    )
