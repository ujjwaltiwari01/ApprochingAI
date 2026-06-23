"""Database helpers for Streamlit via Supabase REST API.

No SQLAlchemy here — all reads use PostgREST (httpx) so the dashboard works with
only SUPABASE_URL + anon/service key, same as import_via_rest.py and preview_emails.py.
"""

import os
from functools import lru_cache

import httpx
from dotenv import load_dotenv

load_dotenv()


def _url() -> str:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def _key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")


def _headers(extra: dict | None = None) -> dict:
    h = {
        "apikey": _key(),
        "Authorization": f"Bearer {_key()}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _count(table: str, filters: str = "") -> int:
    # HEAD + Prefer: count=exact avoids fetching rows — cheap aggregate for metrics
    url = f"{_url()}/rest/v1/{table}?select=id"
    if filters:
        url += f"&{filters}"
    r = httpx.head(url, headers=_headers({"Prefer": "count=exact"}), timeout=30)
    r.raise_for_status()
    content_range = r.headers.get("content-range", "*/0")
    return int(content_range.split("/")[-1])


def test_connection() -> dict:
    leads = _count("leads")
    cache = _count("website_cache")
    return {"leads": leads, "cache": cache, "status": "ok"}


def get_dashboard_metrics() -> dict:
    """Funnel counts for the home dashboard — each metric is a filtered _count()."""
    total = _count("leads")
    sent = _count("leads", "sent_at=not.is.null")
    generated = _count("leads", "status=eq.EMAIL_GENERATED")
    email_sent_status = _count("leads", "status=eq.EMAIL_SENT")
    opened = _count("leads", "opened_at=not.is.null")
    clicked = _count("leads", "clicked_at=not.is.null")
    replied = _count("leads", "replied_at=not.is.null")
    interviews = _count("leads", "status=eq.INTERVIEW")
    hired = _count("leads", "status=eq.HIRED")
    return {
        "total": total,
        "sent": sent,
        "generated": generated,
        "email_sent_status": email_sent_status,
        "opened": opened,
        "clicked": clicked,
        "replied": replied,
        "interviews": interviews,
        "hired": hired,
    }


LEAD_STATUSES = [
    # Mirrors leads.status enum in Supabase — used by Leads page filter dropdown
    "NEW",
    "WEBSITE_ANALYZED",
    "EMAIL_GENERATED",
    "EMAIL_SENT",
    "OPENED",
    "CLICKED",
    "REPLIED",
    "INTERESTED",
    "INTERVIEW",
    "HIRED",
    "BOUNCED",
    "SPAM",
    "FAILED",
    "PAUSED",
]


def fetch_leads(
    status: str | None = None,
    score_min: int = 0,
    lead_source: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Paginated lead list for the Leads page — ordered by outreach priority."""
    params = [
        f"match_score=gte.{score_min}",
        "order=lead_source.desc,match_score.desc,hiring_probability.desc",
        f"limit={limit}",
        "select=company_name,email,country,status,match_score,hiring_probability,lead_source,sent_at,replied_at",
    ]
    if status and status != "All":
        params.append(f"status=eq.{status}")
    if lead_source and lead_source != "All":
        params.append(f"lead_source=eq.{lead_source}")

    url = f"{_url()}/rest/v1/leads?" + "&".join(params)
    r = httpx.get(url, headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()
