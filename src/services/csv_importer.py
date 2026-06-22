import pandas as pd
from loguru import logger
from sqlalchemy import func, select

from src.db.models import Lead, LeadStatus, ScrapeStatus, WebsiteCache, async_session
from src.services.match_scorer import score_lead
from src.utils.url_normalizer import is_valid_email, normalize_email, normalize_website


def _row_to_lead(row: dict) -> dict | None:
    email = normalize_email(row.get("Email"))
    if not email or not is_valid_email(email):
        return None

    match_score, hiring_prob, _ = score_lead(row)
    website = normalize_website(row.get("Website"))

    return {
        "name": row.get("Name", "").strip() or None,
        "email": email,
        "company_name": row.get("Name", "").strip() or None,
        "website": website,
        "country": row.get("Country", "").strip() or None,
        "status": LeadStatus.NEW,
        "match_score": match_score,
        "hiring_probability": hiring_prob,
        "csv_raw": {k: (v if pd.notna(v) else None) for k, v in row.items()},
    }


async def import_csv(csv_path, chunk_size: int = 1000) -> dict:
    from pathlib import Path

    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    stats = {"total": 0, "imported": 0, "updated": 0, "skipped": 0, "errors": 0}

    for chunk in pd.read_csv(csv_path, chunksize=chunk_size, dtype=str, keep_default_na=False):
        async with async_session() as session:
            for _, row in chunk.iterrows():
                stats["total"] += 1
                lead_data = _row_to_lead(row.to_dict())
                if not lead_data:
                    stats["skipped"] += 1
                    continue

                try:
                    result = await session.execute(
                        select(Lead).where(func.lower(Lead.email) == lead_data["email"])
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.company_name = lead_data["company_name"]
                        existing.website = lead_data["website"]
                        existing.country = lead_data["country"]
                        existing.match_score = lead_data["match_score"]
                        existing.hiring_probability = lead_data["hiring_probability"]
                        existing.csv_raw = lead_data["csv_raw"]
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


async def seed_website_cache_from_csv(csv_path, chunk_size: int = 1000) -> int:
    from pathlib import Path

    csv_path = Path(csv_path)
    seeded = 0

    for chunk in pd.read_csv(csv_path, chunksize=chunk_size, dtype=str, keep_default_na=False):
        async with async_session() as session:
            for _, row in chunk.iterrows():
                website = normalize_website(row.get("Website"))
                if not website:
                    continue

                description = row.get("Description", "") or ""
                services = row.get("Services", "") or ""
                team = row.get("Team Bios ", row.get("Team Bios", "")) or ""

                if not description and not services:
                    continue

                existing = await session.execute(
                    select(WebsiteCache).where(WebsiteCache.website == website)
                )
                if existing.scalar_one_or_none():
                    continue

                summary = description[:2000] if description else services[:1000]
                analysis = {
                    "industry": row.get("Industries", ""),
                    "positioning": row.get("Slogan", ""),
                    "services": [s.strip() for s in services.split(",") if s.strip()],
                    "specialization": row.get("Areas of Expertise", ""),
                    "hiring_probability": 0,
                    "summary": summary,
                }

                cache = WebsiteCache(
                    website=website,
                    homepage_content=description[:5000],
                    services_content=services[:3000],
                    about_content=description[:3000],
                    team_content=team[:3000],
                    summary=summary,
                    industry=row.get("Industries", ""),
                    specialization=row.get("Areas of Expertise", ""),
                    scrape_status=ScrapeStatus.CACHED,
                    analysis_json=analysis,
                )
                session.add(cache)
                seeded += 1
            await session.commit()

    logger.info(f"Seeded {seeded} website cache entries from CSV")
    return seeded
