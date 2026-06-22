#!/usr/bin/env python3
"""Import agency CSV into Supabase leads table."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.logging import setup_logging
from src.services.csv_importer import import_csv, seed_website_cache_from_csv

setup_logging()


async def main():
    csv_path = Path(__file__).parent.parent / "21000+ Agency Contact Details - 21K Digital Agencies Contact List.csv"
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])

    print(f"Importing from {csv_path}...")
    stats = await import_csv(csv_path)
    print(f"Import stats: {stats}")

    print("Seeding website cache from CSV...")
    seeded = await seed_website_cache_from_csv(csv_path)
    print(f"Seeded {seeded} cache entries")


if __name__ == "__main__":
    asyncio.run(main())
