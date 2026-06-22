"""Database helpers for Streamlit via Supabase REST API."""

import os
from functools import lru_cache

import httpx
from dotenv import load_dotenv

load_dotenv()


def _url() -> str:
    return os.getenv("SUPABASE_URL", "").rstrip("/")


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
    total = _count("leads")
    sent = _count("leads", "sent_at=not.is.null")
    opened = _count("leads", "opened_at=not.is.null")
    clicked = _count("leads", "clicked_at=not.is.null")
    replied = _count("leads", "replied_at=not.is.null")
    interviews = _count("leads", "status=eq.INTERVIEW")
    hired = _count("leads", "status=eq.HIRED")
    return {
        "total": total,
        "sent": sent,
        "opened": opened,
        "clicked": clicked,
        "replied": replied,
        "interviews": interviews,
        "hired": hired,
    }


def fetch_leads(status: str | None = None, score_min: int = 0, limit: int = 100) -> list[dict]:
    params = [
        f"match_score=gte.{score_min}",
        "order=match_score.desc",
        f"limit={limit}",
        "select=company_name,email,country,status,match_score,hiring_probability,sent_at,replied_at",
    ]
    if status and status != "All":
        params.append(f"status=eq.{status}")

    url = f"{_url()}/rest/v1/leads?" + "&".join(params)
    r = httpx.get(url, headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()
