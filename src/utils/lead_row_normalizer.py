"""Normalize agency-list and USA owner CSV rows into a canonical lead shape."""

from __future__ import annotations

LEAD_SOURCE_AGENCY_LIST = "agency_list"
LEAD_SOURCE_USA_OWNERS = "usa_owners"

GENERIC_EMAIL_PREFIXES = (
    "info@",
    "hello@",
    "contact@",
    "sales@",
    "support@",
    "admin@",
    "office@",
    "team@",
    "enquiries@",
    "inquiries@",
)


def detect_lead_source(row: dict) -> str:
    if (row.get("email") or row.get("Email")) and (
        row.get("Company Name for Emails") or row.get("co_name") or row.get("Seniority")
    ):
        return LEAD_SOURCE_USA_OWNERS
    return LEAD_SOURCE_AGENCY_LIST


def _first_nonempty(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def scoring_fields_from_row(row: dict) -> dict:
    """Map either CSV format into fields used by match_scorer."""
    source = detect_lead_source(row)
    if source == LEAD_SOURCE_USA_OWNERS:
        title = _first_nonempty(row, "Title")
        seniority = _first_nonempty(row, "Seniority")
        departments = _first_nonempty(row, "Departments")
        return {
            "services": _first_nonempty(row, "Keywords"),
            "description": _first_nonempty(row, "SEO Description"),
            "expertise": f"{title} {seniority} {departments}".strip(),
            "industries": _first_nonempty(row, "Industry"),
            "team_bios": "",
            "title": title,
            "seniority": seniority,
            "email": _first_nonempty(row, "email", "Email"),
            "lead_source": source,
        }

    return {
        "services": _first_nonempty(row, "Services"),
        "description": _first_nonempty(row, "Description"),
        "expertise": _first_nonempty(row, "Areas of Expertise"),
        "industries": _first_nonempty(row, "Industries"),
        "team_bios": _first_nonempty(row, "Team Bios ", "Team Bios"),
        "title": "",
        "seniority": "",
        "email": _first_nonempty(row, "Email", "email"),
        "lead_source": source,
    }


def normalize_lead_fields(row: dict) -> dict:
    """Canonical import fields shared by both CSV formats."""
    source = detect_lead_source(row)
    scoring = scoring_fields_from_row(row)

    if source == LEAD_SOURCE_USA_OWNERS:
        first = _first_nonempty(row, "Name")
        last = _first_nonempty(row, "Last Name")
        person_name = f"{first} {last}".strip() or None
        company_name = _first_nonempty(row, "Company Name for Emails", "co_name", "Company Name") or None
        return {
            "name": person_name,
            "email_key": "email",
            "company_name": company_name,
            "website_key": "website",
            "country": _first_nonempty(row, "Country") or None,
            "lead_source": source,
            "scoring": scoring,
        }

    return {
        "name": _first_nonempty(row, "Name") or None,
        "email_key": "Email",
        "company_name": _first_nonempty(row, "Name") or None,
        "website_key": "Website",
        "country": _first_nonempty(row, "Country") or None,
        "lead_source": source,
        "scoring": scoring,
    }


def is_direct_decision_maker_email(email: str) -> bool:
    lower = email.lower().strip()
    return bool(lower) and not any(lower.startswith(prefix) for prefix in GENERIC_EMAIL_PREFIXES)


def recipient_first_name_from_lead(lead) -> str | None:
    """Return first name for email greeting when the lead is a named USA contact."""
    source = getattr(lead, "lead_source", None)
    if source is None and isinstance(lead, dict):
        source = lead.get("lead_source")

    if source != LEAD_SOURCE_USA_OWNERS:
        return None

    name = getattr(lead, "name", None)
    if name is None and isinstance(lead, dict):
        name = lead.get("name")
        if not name:
            raw = lead.get("csv_raw") or {}
            name = raw.get("Name")

    if not name:
        return None

    first = str(name).strip().split()[0]
    if first and len(first) >= 2 and first[0].isalpha():
        return first
    return None


def recipient_greeting_instruction(recipient_first_name: str | None) -> str:
    if recipient_first_name:
        return (
            f"Recipient first name: {recipient_first_name}. "
            f"You MUST open the email body with 'Hi {recipient_first_name},' on its own line "
            "before paragraph 1."
        )
    return (
        "No recipient first name is available. Do not use 'Hi there', 'Dear team', "
        "or other generic greetings. Start directly with the agency observation."
    )
