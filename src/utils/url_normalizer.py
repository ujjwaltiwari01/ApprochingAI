"""Canonical URL and email normalization for deduplication and cache keys.

Design: one canonical form per website/email so the same agency imported from
different CSV rows or scrape passes maps to a single cache row. We strip scheme
noise (www, trailing slashes) rather than full canonicalization — good enough
for outreach dedupe without pulling in a heavy URL library.
"""

import re
from urllib.parse import urlparse, urlunparse


def normalize_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    # Lowercase for case-insensitive uniqueness checks and Brevo recipient keys.
    return email.strip().lower()


def normalize_website(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    url = url.strip()
    # Bare domains from CSVs get https so urlparse has a netloc to work with.
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    clean_path = parsed.path.rstrip("/") or "/"
    # Drop query/fragment — they rarely identify a different agency site.
    normalized = urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower().removeprefix("www."), clean_path, "", "", "")
    )
    return normalized.rstrip("/")


def extract_domain(url: str | None) -> str | None:
    """Domain-only key for grouping leads that share a parent company site."""
    if not url:
        return None
    normalized = normalize_website(url)
    if not normalized:
        return None
    return urlparse(normalized).netloc


def is_valid_email(email: str | None) -> bool:
    if not email:
        return False
    # Lightweight regex — not RFC-complete; catches obvious CSV garbage before send.
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))
