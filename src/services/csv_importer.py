"""CSV ingestion into Lead rows and optional WebsiteCache seeding.

Role in pipeline: entry point for lead data — reads chunked CSVs, normalizes
heterogeneous column names, scores each row, upserts by email, and can pre-populate
``WebsiteCache`` from CSV text to skip Playwright on first touch.

Why this design (interview angle): real lead files are messy (varying headers,
duplicate emails across lists). Chunked pandas reads keep memory flat on 50k+
rows. Email-level upsert with merge rules preserves outreach state (don't reset
a lead already emailed) while letting better-scored re-imports win.

Key decisions:
- ``dtype=str`` + ``keep_default_na=False`` — avoids pandas mangling emails/phones.
- Score at import time — prioritization works before any async scrape job runs.
- ``seed_website_cache_from_csv`` — trades imperfect CSV copy for zero-latency analysis on cache hit.
- Per-chunk DB session commit — balances transaction size vs failure blast radius.
"""

import pandas as pd
from loguru import logger
from sqlalchemy import func, select

from src.db.models import Lead, LeadStatus, ScrapeStatus, WebsiteCache, async_session
from src.services.match_scorer import score_lead
from src.utils.lead_row_normalizer import LEAD_SOURCE_USA_OWNERS, normalize_lead_fields, scoring_fields_from_row
from src.utils.url_normalizer import is_valid_email, normalize_email, normalize_website


def _row_to_lead(row: dict) -> dict | None:
    fields = normalize_lead_fields(row)
    email = normalize_email(row.get(fields["email_key"]))
    if not email or not is_valid_email(email):
        return None

    match_score, hiring_prob, _ = score_lead(row)
    website = normalize_website(row.get(fields["website_key"]))

    return {
        "name": fields["name"],
        "email": email,
        "company_name": fields["company_name"],
        "website": website,
        "country": fields["country"],
        "status": LeadStatus.NEW,
        "match_score": match_score,
        "hiring_probability": hiring_prob,
        "lead_source": fields["lead_source"],
        # Preserve full row for later CSV fallback when Playwright is skipped or fails.
        "csv_raw": {k: (v if pd.notna(v) else None) for k, v in row.items()},
    }


def _merge_existing_lead(existing: Lead, lead_data: dict) -> None:
    existing.name = lead_data["name"] or existing.name
    existing.company_name = lead_data["company_name"] or existing.company_name
    existing.website = lead_data["website"] or existing.website
    existing.country = lead_data["country"] or existing.country
    existing.csv_raw = lead_data["csv_raw"]

    # Keep the higher priority score; USA owners win ties on same score.
    new_score = lead_data["match_score"]
    if new_score > existing.match_score:
        existing.match_score = new_score
        existing.hiring_probability = lead_data["hiring_probability"]
        existing.lead_source = lead_data["lead_source"]
    elif (
        new_score == existing.match_score
        and lead_data["lead_source"] == LEAD_SOURCE_USA_OWNERS
        and existing.lead_source != LEAD_SOURCE_USA_OWNERS
    ):
        existing.hiring_probability = max(existing.hiring_probability, lead_data["hiring_probability"])
        existing.lead_source = LEAD_SOURCE_USA_OWNERS
    elif lead_data["lead_source"] == LEAD_SOURCE_USA_OWNERS and existing.status == LeadStatus.NEW:
        existing.hiring_probability = max(existing.hiring_probability, lead_data["hiring_probability"])


async def import_csv(csv_path, chunk_size: int = 1000) -> dict:
    from pathlib import Path

    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    stats = {"total": 0, "imported": 0, "updated": 0, "skipped": 0, "errors": 0}

    # Chunked read: O(chunk_size) memory — required for multi-GB exports on CI runners.
    for chunk in pd.read_csv(csv_path, chunksize=chunk_size, dtype=str, keep_default_na=False):
        async with async_session() as session:
            for _, row in chunk.iterrows():
                stats["total"] += 1
                lead_data = _row_to_lead(row.to_dict())
                if not lead_data:
                    stats["skipped"] += 1
                    continue

                try:
                    # Case-insensitive email match — same person may appear with different casing across files.
                    result = await session.execute(
                        select(Lead).where(func.lower(Lead.email) == lead_data["email"])
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        _merge_existing_lead(existing, lead_data)
                        stats["updated"] += 1
                    else:
                        session.add(Lead(**lead_data))
                        stats["imported"] += 1
                except Exception as exc:
                    logger.error(f"Failed to import {lead_data.get('email')}: {exc}")
                    stats["errors"] += 1

            await session.commit()

    logger.info(f"Import complete: {stats}")
    return stats


def _cache_fields_from_row(row: dict) -> dict | None:
    scoring = scoring_fields_from_row(row)
    fields = normalize_lead_fields(row)
    website = normalize_website(row.get(fields["website_key"]))
    if not website:
        return None

    description = scoring.get("description", "")
    services = scoring.get("services", "")
    team = scoring.get("team_bios", "")
    # Need some descriptive text or seeding adds no value for personalization.
    if not description and not services:
        return None

    summary = description[:2000] if description else services[:1000]
    return {
        "website": website,
        "description": description,
        "services": services,
        "team": team,
        "summary": summary,
        "industry": scoring.get("industries", ""),
        "specialization": scoring.get("expertise", ""),
    }


async def seed_website_cache_from_csv(csv_path, chunk_size: int = 1000) -> int:
    from pathlib import Path

    csv_path = Path(csv_path)
    seeded = 0

    for chunk in pd.read_csv(csv_path, chunksize=chunk_size, dtype=str, keep_default_na=False):
        async with async_session() as session:
            for _, row in chunk.iterrows():
                cache_fields = _cache_fields_from_row(row.to_dict())
                if not cache_fields:
                    continue

                existing = await session.execute(
                    select(WebsiteCache).where(WebsiteCache.website == cache_fields["website"])
                )
                if existing.scalar_one_or_none():
                    continue

                analysis = {
                    "industry": cache_fields["industry"],
                    "positioning": "",
                    "services": [s.strip() for s in cache_fields["services"].split(",") if s.strip()],
                    "specialization": cache_fields["specialization"],
                    "hiring_probability": 0,
                    "summary": cache_fields["summary"],
                }

                # Mark CACHED so analyzer treats this like a successful scrape without hitting the site.
                cache = WebsiteCache(
                    website=cache_fields["website"],
                    homepage_content=cache_fields["description"][:5000],
                    services_content=cache_fields["services"][:3000],
                    about_content=cache_fields["description"][:3000],
                    team_content=cache_fields["team"][:3000],
                    summary=cache_fields["summary"],
                    industry=cache_fields["industry"],
                    specialization=cache_fields["specialization"],
                    scrape_status=ScrapeStatus.CACHED,
                    analysis_json=analysis,
                )
                session.add(cache)
                seeded += 1
            await session.commit()

    logger.info(f"Seeded {seeded} website cache entries from CSV")
    return seeded
