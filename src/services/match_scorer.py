CATEGORY_SCORES = {
    "ai_agency": 95,
    "automation_agency": 90,
    "web_development": 85,
    "marketing": 80,
    "consulting": 70,
    "general_business": 50,
    "unrelated": 20,
}

AI_KEYWORDS = [
    "ai development", "artificial intelligence", "machine learning", "llm",
    "generative ai", "chatbot", "nlp", "deep learning", "ai agent",
    "computer vision", "data science", "ai expertise",
]

AUTOMATION_KEYWORDS = [
    "automation", "workflow", "rpa", "process automation", "no code",
    "low code", "integration", "orchestration",
]

WEB_DEV_KEYWORDS = [
    "web development", "web design", "software development", "mobile app",
    "full stack", "frontend", "backend", "react", "node.js",
]

MARKETING_KEYWORDS = [
    "digital marketing", "seo", "ppc", "social media", "content marketing",
    "email marketing", "branding", "advertising",
]

CONSULTING_KEYWORDS = [
    "consulting", "strategy", "advisory", "digital transformation",
    "business consulting", "it consulting",
]

HIRING_SIGNALS = [
    "hiring", "join our team", "careers", "we're growing", "open positions",
    "looking for", "recruit", "talent", "job opening",
]


def _text_contains(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def classify_agency(services: str = "", description: str = "", expertise: str = "", industries: str = "") -> tuple[str, int]:
    combined = f"{services} {description} {expertise} {industries}".lower()

    if _text_contains(combined, AI_KEYWORDS):
        return "ai_agency", CATEGORY_SCORES["ai_agency"]
    if _text_contains(combined, AUTOMATION_KEYWORDS):
        return "automation_agency", CATEGORY_SCORES["automation_agency"]
    if _text_contains(combined, WEB_DEV_KEYWORDS):
        return "web_development", CATEGORY_SCORES["web_development"]
    if _text_contains(combined, MARKETING_KEYWORDS):
        return "marketing", CATEGORY_SCORES["marketing"]
    if _text_contains(combined, CONSULTING_KEYWORDS):
        return "consulting", CATEGORY_SCORES["consulting"]
    if len(combined.strip()) > 50:
        return "general_business", CATEGORY_SCORES["general_business"]
    return "unrelated", CATEGORY_SCORES["unrelated"]


def compute_hiring_probability(description: str = "", team_bios: str = "", services: str = "") -> int:
    combined = f"{description} {team_bios} {services}".lower()
    score = 0
    if _text_contains(combined, HIRING_SIGNALS):
        score += 40
    if _text_contains(combined, AI_KEYWORDS):
        score += 30
    if "growing" in combined or "expand" in combined:
        score += 15
    if "startup" in combined or "scale" in combined:
        score += 10
    return min(score, 100)


def score_lead(row: dict) -> tuple[int, int, str]:
    category, match_score = classify_agency(
        services=row.get("Services", "") or "",
        description=row.get("Description", "") or "",
        expertise=row.get("Areas of Expertise", "") or "",
        industries=row.get("Industries", "") or "",
    )
    hiring_prob = compute_hiring_probability(
        description=row.get("Description", "") or "",
        team_bios=row.get("Team Bios ", row.get("Team Bios", "")) or "",
        services=row.get("Services", "") or "",
    )
    # Boost match score for high hiring probability
    if hiring_prob >= 40:
        match_score = min(match_score + 5, 100)
    return match_score, hiring_prob, category
