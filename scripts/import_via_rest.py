#!/usr/bin/env python3
"""Import agency CSV into Supabase via REST API (no DATABASE_URL password needed)."""

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.match_scorer import score_lead
from src.utils.url_normalizer import is_valid_email, normalize_email, normalize_website

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
BATCH_SIZE = 500


def row_to_record(row: dict) -> dict | None:
    email = normalize_email(row.get("Email"))
    if not email or not is_valid_email(email):
        return None

    match_score, hiring_prob, _ = score_lead(row)
    website = normalize_website(row.get("Website"))
    csv_raw = {k: (v if pd.notna(v) else None) for k, v in row.items()}

    return {
        "name": (row.get("Name") or "").strip() or None,
        "email": email,
        "company_name": (row.get("Name") or "").strip() or None,
        "website": website,
        "country": (row.get("Country") or "").strip() or None,
        "status": "NEW",
        "match_score": match_score,
        "hiring_probability": hiring_prob,
        "csv_raw": csv_raw,
    }


def cache_row_to_record(row: dict) -> dict | None:
    website = normalize_website(row.get("Website"))
    if not website:
        return None

    description = row.get("Description", "") or ""
    services = row.get("Services", "") or ""
    team = row.get("Team Bios ", row.get("Team Bios", "")) or ""
    if not description and not services:
        return None

    summary = description[:2000] if description else services[:1000]
    return {
        "website": website,
        "homepage_content": description[:5000] or None,
        "services_content": services[:3000] or None,
        "about_content": description[:3000] or None,
        "team_content": team[:3000] or None,
        "summary": summary,
        "industry": row.get("Industries", "") or None,
        "specialization": row.get("Areas of Expertise", "") or None,
        "scrape_status": "cached",
        "analysis_json": {
            "industry": row.get("Industries", ""),
            "positioning": row.get("Slogan", ""),
            "services": [s.strip() for s in services.split(",") if s.strip()],
            "specialization": row.get("Areas of Expertise", ""),
            "hiring_probability": 0,
            "summary": summary,
        },
    }


def upsert_batch(table: str, records: list, on_conflict: str = "email") -> None:
    import httpx

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": f"resolution=merge-duplicates,return=minimal",
    }
    if table == "leads":
        headers["Prefer"] = "resolution=ignore-duplicates,return=minimal"

    response = httpx.post(url, headers=headers, json=records, timeout=120)
    if response.status_code >= 400:
        raise RuntimeError(f"Batch insert failed ({response.status_code}): {response.text[:500]}")


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_ANON_KEY in .env")
        sys.exit(1)

    csv_path = Path(__file__).parent.parent / "21000+ Agency Contact Details - 21K Digital Agencies Contact List.csv"
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])

    print(f"Importing leads from {csv_path.name}...")
    lead_stats = {"total": 0, "imported": 0, "skipped": 0, "errors": 0}
    batch: list = []
    seen_emails: set = set()

    for chunk in pd.read_csv(csv_path, chunksize=2000, dtype=str, keep_default_na=False):
        for _, row in chunk.iterrows():
            lead_stats["total"] += 1
            record = row_to_record(row.to_dict())
            if not record:
                lead_stats["skipped"] += 1
                continue
            if record["email"] in seen_emails:
                lead_stats["skipped"] += 1
                continue
            seen_emails.add(record["email"])
            batch.append(record)

            if len(batch) >= BATCH_SIZE:
                try:
                    upsert_batch("leads", batch)
                    lead_stats["imported"] += len(batch)
                    print(f"  Leads imported: {lead_stats['imported']}")
                except Exception as exc:
                    lead_stats["errors"] += len(batch)
                    print(f"  Batch error: {exc}")
                batch = []
                time.sleep(0.2)

    if batch:
        try:
            upsert_batch("leads", batch)
            lead_stats["imported"] += len(batch)
        except Exception as exc:
            lead_stats["errors"] += len(batch)
            print(f"  Final batch error: {exc}")

    print(f"Lead import done: {lead_stats}")

    print("Seeding website_cache from CSV...")
    cache_stats = {"seeded": 0, "skipped": 0, "errors": 0}
    cache_batch: list = []
    seen_sites: set = set()

    for chunk in pd.read_csv(csv_path, chunksize=2000, dtype=str, keep_default_na=False):
        for _, row in chunk.iterrows():
            record = cache_row_to_record(row.to_dict())
            if not record:
                cache_stats["skipped"] += 1
                continue
            if record["website"] in seen_sites:
                continue
            seen_sites.add(record["website"])
            cache_batch.append(record)

            if len(cache_batch) >= BATCH_SIZE:
                try:
                    upsert_batch("website_cache", cache_batch)
                    cache_stats["seeded"] += len(cache_batch)
                    print(f"  Cache seeded: {cache_stats['seeded']}")
                except Exception as exc:
                    cache_stats["errors"] += len(cache_batch)
                    print(f"  Cache batch error: {exc}")
                cache_batch = []
                time.sleep(0.2)

    if cache_batch:
        try:
            upsert_batch("website_cache", cache_batch)
            cache_stats["seeded"] += len(cache_batch)
        except Exception as exc:
            cache_stats["errors"] += len(cache_batch)
            print(f"  Final cache error: {exc}")

    print(f"Cache seed done: {cache_stats}")


if __name__ == "__main__":
    main()
