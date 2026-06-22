#!/usr/bin/env python3
"""Generate email previews for real leads — no sending."""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

from src.core.config import get_settings

get_settings.cache_clear()

from src.services.email_generator import EmailGenerator
from src.utils.url_normalizer import normalize_website


def _supabase_headers() -> dict:
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def fetch_top_leads(limit: int, min_score: int) -> list[dict]:
    url = (
        f"{os.getenv('SUPABASE_URL').rstrip('/')}/rest/v1/leads"
        f"?status=eq.NEW&match_score=gte.{min_score}"
        f"&order=match_score.desc&limit={limit}"
        "&select=id,company_name,email,website,country,match_score,hiring_probability,csv_raw"
    )
    r = httpx.get(url, headers=_supabase_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_cache_analysis(website: str) -> dict | None:
    normalized = normalize_website(website)
    if not normalized:
        return None
    url = (
        f"{os.getenv('SUPABASE_URL').rstrip('/')}/rest/v1/website_cache"
        f"?website=eq.{normalized}"
        "&select=summary,industry,specialization,analysis_json,homepage_content"
    )
    r = httpx.get(url, headers=_supabase_headers(), timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    row = rows[0]
    if row.get("analysis_json"):
        return row["analysis_json"]
    return {
        "industry": row.get("industry", ""),
        "positioning": "",
        "services": [],
        "specialization": row.get("specialization", ""),
        "hiring_probability": 0,
        "summary": row.get("summary") or (row.get("homepage_content") or "")[:1000],
    }


def analysis_from_csv(csv_raw: dict | None, hiring_prob: int) -> dict:
    raw = csv_raw or {}
    description = raw.get("Description", "") or ""
    services = raw.get("Services", "") or ""
    return {
        "industry": raw.get("Industries", ""),
        "positioning": raw.get("Slogan", ""),
        "services": [s.strip() for s in services.split(",") if s.strip()],
        "specialization": raw.get("Areas of Expertise", ""),
        "hiring_probability": hiring_prob,
        "summary": description[:1000] or services[:500],
    }


def get_agency_analysis(lead: dict) -> dict:
    if lead.get("website"):
        cached = fetch_cache_analysis(lead["website"])
        if cached and cached.get("summary"):
            return cached
    return analysis_from_csv(lead.get("csv_raw"), lead.get("hiring_probability", 0))


def word_count(text: str) -> int:
    return len(text.split())


def format_preview_block(
    lead: dict,
    subject: str,
    body: str,
    provider: str,
    validation: dict,
    analysis: dict,
    subject_candidates: list[str] | None = None,
) -> str:
    valid = validation["passed"]
    reasons = validation.get("reasons", [])
    lines = [
        f"## {lead.get('company_name') or 'Unknown Agency'}",
        "",
        f"- **Email:** {lead.get('email')}",
        f"- **Website:** {lead.get('website') or 'N/A'}",
        f"- **Country:** {lead.get('country') or 'N/A'}",
        f"- **Match score:** {lead.get('match_score')} | **Hiring prob:** {lead.get('hiring_probability')}",
        f"- **LLM provider:** {provider}",
        f"- **Validation:** {'PASSED' if valid else 'FAILED'}",
        f"- **Word count:** {validation.get('word_count', word_count(body))}",
    ]
    if reasons:
        lines.append(f"- **Validation notes:** {', '.join(reasons)}")
    if subject_candidates:
        lines.append("- **Subject candidates:**")
        for i, s in enumerate(subject_candidates, 1):
            marker = " ← selected" if s == subject else ""
            lines.append(f"  {i}. {s}{marker}")
    lines.extend([
        "",
        "### Agency insight used",
        f"> {(analysis.get('summary') or analysis.get('positioning') or 'N/A')[:300]}",
        "",
        f"### Subject: {subject}",
        "",
        "### Email body",
        "",
        body,
        "",
        "---",
        "",
    ])
    return "\n".join(lines)


async def generate_previews(count: int, min_score: int, include_followup: bool) -> Path:

    leads = fetch_top_leads(count, min_score)
    if not leads:
        raise SystemExit(f"No NEW leads found with match_score >= {min_score}")

    generator = EmailGenerator()

    output_dir = Path(__file__).parent.parent / "previews"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"email_preview_{timestamp}.md"

    sections = [
        "# Email Preview — Real Leads (NOT SENT)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Leads: {len(leads)} | Min score: {min_score} | Prompts: `prompts/master_email.txt`, `prompts/subject_lines.txt`",
        "",
        "> Review these copies before enabling live sending.",
        "",
        "---",
        "",
    ]

    print(f"Generating previews for {len(leads)} leads...\n")

    for i, lead in enumerate(leads, 1):
        company = lead.get("company_name") or "Agency"
        print(f"[{i}/{len(leads)}] {company} ({lead.get('email')})...")

        analysis = get_agency_analysis(lead)
        subject, body, provider, valid, subject_candidates = await generator.generate_initial_email(
            company, analysis
        )
        validation = generator.validate_email_details(subject, body, analysis)

        sections.append(
            format_preview_block(lead, subject, body, provider, validation, analysis, subject_candidates)
        )
        print(f"  -> {provider} | valid={validation['passed']} | words={validation['word_count']} | subject: {subject}")
        if validation.get("reasons"):
            print(f"     notes: {', '.join(validation['reasons'])}")

        if include_followup:
            fu_subject, fu_body, fu_provider, fu_valid = await generator.generate_followup_email(
                company_name=company,
                agency_analysis=analysis,
                followup_number=1,
                previous_subject=subject,
                engagement_type="opened_no_reply",
            )
            sections.append("### Follow-up #1 (preview)")
            sections.append("")
            sections.append(f"**Subject:** {fu_subject}")
            sections.append("")
            sections.append(fu_body)
            sections.append("")
            sections.append(f"*Provider: {fu_provider} | Valid: {fu_valid} | Words: {word_count(fu_body)}*")
            sections.append("")
            sections.append("---")
            sections.append("")

    out_path.write_text("\n".join(sections), encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview generated outreach emails for real leads")
    parser.add_argument("-n", "--count", type=int, default=5, help="Number of leads (default: 5)")
    parser.add_argument("-s", "--min-score", type=int, default=85, help="Minimum match score (default: 85)")
    parser.add_argument("--followup", action="store_true", help="Also generate follow-up #1 previews")
    args = parser.parse_args()

    out_path = asyncio.run(generate_previews(args.count, args.min_score, args.followup))
    print(f"\nPreview saved to: {out_path}")
    print("Open that file to review all email copies before sending.")


if __name__ == "__main__":
    main()
