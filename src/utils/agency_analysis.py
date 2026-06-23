"""Build agency analysis dicts from website cache or CSV (both list formats).

This module is the bridge between heterogeneous lead data (scraped site cache vs
two CSV schemas) and the stable dict shape the email LLM prompt expects. Keeping
that contract here avoids scattering field-mapping logic across the pipeline.
"""

from src.utils.lead_row_normalizer import scoring_fields_from_row


def agency_analysis_from_csv_raw(raw: dict | None, hiring_probability: int = 0) -> dict:
    """Map agency-list or USA-owner csv_raw into the analysis shape used by the LLM."""
    raw = raw or {}
    # Reuse lead_row_normalizer so CSV column quirks live in one place.
    scoring = scoring_fields_from_row(raw)

    description = scoring.get("description", "") or ""
    services_text = scoring.get("services", "") or ""
    services = [s.strip() for s in services_text.split(",") if s.strip()]
    expertise = scoring.get("expertise", "") or ""

    # Fallback chain: richest text first, with hard caps to bound prompt size.
    summary = description[:1000] or services_text[:500] or expertise[:500]

    return {
        "industry": scoring.get("industries", ""),
        "positioning": raw.get("Slogan", "") or raw.get("SEO Description", "")[:200] or "",
        "services": services,
        "specialization": expertise,
        "hiring_probability": hiring_probability,
        "summary": summary,
    }


def merge_analysis(primary: dict | None, fallback: dict) -> dict:
    """Prefer primary cache analysis but fill empty fields from CSV fallback."""
    # Start from CSV so we always have *something* even when scrape/cache missed.
    merged = dict(fallback)
    if primary:
        # Non-empty primary wins — scraped content is usually more accurate than CSV blurbs.
        merged.update({k: v for k, v in primary.items() if v not in (None, "", [], {})})
    # Second pass: explicit keys where primary left holes the fallback can fill.
    for key in ("summary", "industry", "specialization", "positioning", "services"):
        if not merged.get(key) and fallback.get(key):
            merged[key] = fallback[key]
    # Synthesize summary last so emails still get a hook when both sources lack one.
    if not merged.get("summary"):
        merged["summary"] = (
            merged.get("positioning")
            or merged.get("specialization")
            or ", ".join(merged.get("services") or [])[:500]
            or ""
        )
    return merged


def cache_row_to_analysis(row: dict) -> dict:
    """Normalize a website_cache REST/ORM row into analysis dict."""
    # Prefer structured LLM output when present; else derive from raw scrape columns.
    if row.get("analysis_json"):
        analysis = dict(row["analysis_json"])
    else:
        analysis = {
            "industry": row.get("industry", ""),
            "positioning": "",
            "services": [],
            "specialization": row.get("specialization", ""),
            "hiring_probability": 0,
            "summary": "",
        }

    # Same summary fallback pattern as CSV path — keeps merge_analysis predictable.
    if not analysis.get("summary"):
        analysis["summary"] = (
            row.get("summary")
            or (row.get("homepage_content") or "")[:1000]
            or (row.get("services_content") or "")[:500]
        )
    # Cap service list length; long comma-separated scrape blobs blow up token budgets.
    if not analysis.get("services") and row.get("services_content"):
        analysis["services"] = [
            s.strip() for s in str(row["services_content"]).split(",") if s.strip()
        ][:12]
    return analysis
