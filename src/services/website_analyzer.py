import asyncio
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
from loguru import logger
from sqlalchemy import select

from src.core.config import get_settings
from src.db.models import Lead, LeadStatus, ScrapeStatus, WebsiteCache, async_session
from src.services.llm_client import LLMClient
from src.utils.agency_analysis import agency_analysis_from_csv_raw

PAGES = ["/", "/about", "/services", "/team", "/case-studies", "/blog", "/capabilities"]
PAGE_KEYS = {
    "/": "homepage_content",
    "/about": "about_content",
    "/services": "services_content",
    "/team": "team_content",
}


class WebsiteAnalyzer:
    def __init__(self):
        self.settings = get_settings()
        self.llm = LLMClient()
        self.semaphore = asyncio.Semaphore(self.settings.playwright_concurrency)

    async def analyze_for_lead(self, lead: Lead) -> dict:
        website = normalize_website(lead.website)
        if not website:
            return self._fallback_from_csv(lead)

        cached = await self._get_cache(website)
        if cached:
            return cached

        if self.settings.skip_playwright:
            logger.info(f"Playwright skipped for {website}, using CSV fallback")
            return self._fallback_from_csv(lead)

        async with self.semaphore:
            return await self._scrape_and_cache(website, lead)

    async def get_cached_analysis(self, lead: Lead) -> dict | None:
        """Cache-only lookup — no Playwright (for follow-ups on server)."""
        website = normalize_website(lead.website)
        if not website:
            return self._fallback_from_csv(lead)
        cached = await self._get_cache(website)
        if cached:
            return cached
        if lead.csv_raw:
            return self._fallback_from_csv(lead)
        return None

    async def _get_cache(self, website: str) -> dict | None:
        ttl = timedelta(days=self.settings.cache_ttl_days)
        cutoff = datetime.now(timezone.utc) - ttl

        async with async_session() as session:
            result = await session.execute(
                select(WebsiteCache).where(WebsiteCache.website == website)
            )
            cache = result.scalar_one_or_none()
            if cache and cache.last_scraped.replace(tzinfo=timezone.utc) > cutoff:
                logger.info(f"Cache hit for {website}")
                return cache.analysis_json or {
                    "industry": cache.industry,
                    "positioning": cache.summary,
                    "services": [],
                    "specialization": cache.specialization,
                    "hiring_probability": 0,
                    "summary": cache.summary,
                }
        return None

    async def _scrape_and_cache(self, website: str, lead: Lead) -> dict:
        page_contents: dict[str, str] = {}

        for attempt in range(3):
            try:
                page_contents = await self._scrape_pages(website)
                break
            except Exception as exc:
                logger.warning(f"Scrape attempt {attempt + 1} failed for {website}: {exc}")
                if attempt == 2:
                    return self._fallback_from_csv(lead)

        analysis = await self.llm.summarize_website(page_contents)

        async with async_session() as session:
            cache = WebsiteCache(
                website=website,
                homepage_content=page_contents.get("homepage_content"),
                services_content=page_contents.get("services_content"),
                about_content=page_contents.get("about_content"),
                team_content=page_contents.get("team_content"),
                summary=analysis.get("summary"),
                industry=analysis.get("industry"),
                specialization=analysis.get("specialization"),
                scrape_status=ScrapeStatus.SUCCESS,
                analysis_json=analysis,
            )
            session.add(cache)
            await session.commit()

        return analysis

    async def _scrape_pages(self, base_url: str) -> dict[str, str]:
        from playwright.async_api import async_playwright

        contents: dict[str, str] = {}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            for path in PAGES:
                url = base_url if path == "/" else f"{base_url.rstrip('/')}{path}"
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    if response and response.status < 400:
                        html = await page.content()
                        text = self._extract_text(html)
                        if text:
                            key = PAGE_KEYS.get(path, "homepage_content")
                            if key not in contents or path == "/":
                                contents[key] = text
                except Exception:
                    continue

            await browser.close()

        return contents

    def _extract_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return " ".join(text.split())[:5000]

    def _fallback_from_csv(self, lead: Lead) -> dict:
        return agency_analysis_from_csv_raw(lead.csv_raw, lead.hiring_probability)

    async def update_lead_status(self, lead_id, analysis: dict) -> None:
        async with async_session() as session:
            result = await session.execute(select(Lead).where(Lead.id == lead_id))
            lead = result.scalar_one_or_none()
            if lead:
                lead.status = LeadStatus.WEBSITE_ANALYZED
                lead.hiring_probability = analysis.get("hiring_probability", lead.hiring_probability)
                await session.commit()
