import re
from urllib.parse import urlparse, urlunparse


def normalize_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.strip().lower()


def normalize_website(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    clean_path = parsed.path.rstrip("/") or "/"
    normalized = urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower().removeprefix("www."), clean_path, "", "", "")
    )
    return normalized.rstrip("/")


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    normalized = normalize_website(url)
    if not normalized:
        return None
    return urlparse(normalized).netloc


def is_valid_email(email: str | None) -> bool:
    if not email:
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))
