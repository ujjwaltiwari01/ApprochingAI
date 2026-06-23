from src.utils.lead_row_normalizer import (
    LEAD_SOURCE_USA_OWNERS,
    is_direct_decision_maker_email,
    scoring_fields_from_row,
)

CATEGORY_SCORES = {
    "ai_agency": 95,
    "automation_agency": 90,
    "web_development": 85,
    "marketing": 80,
    "consulting": 70,
    "general_business": 50,
    "unrelated": 20,
}

USA_OWNER_SOURCE_BOOST = 20
USA_DECISION_MAKER_BOOST = 8
USA_DIRECT_EMAIL_BOOST = 5
USA_HIRING_DECISION_MAKER_BOOST = 15

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

DECISION_MAKER_KEYWORDS = [
    "c suite", "founder", "owner", "ceo", "cmo", "cto", "president",
    "director", "vp", "partner", "head of",
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


def _apply_usa_owner_boosts(match_score: int, hiring_prob: int, scoring: dict) -> tuple[int, int]:
    if scoring.get("lead_source") != LEAD_SOURCE_USA_OWNERS:
        return match_score, hiring_prob

    match_score = min(match_score + USA_OWNER_SOURCE_BOOST, 100)

    role_text = f"{scoring.get('title', '')} {scoring.get('seniority', '')} {scoring.get('expertise', '')}".lower()
    if _text_contains(role_text, DECISION_MAKER_KEYWORDS):
        match_score = min(match_score + USA_DECISION_MAKER_BOOST, 100)
        hiring_prob = min(hiring_prob + USA_HIRING_DECISION_MAKER_BOOST, 100)

    email = scoring.get("email", "")
    if is_direct_decision_maker_email(email):
        match_score = min(match_score + USA_DIRECT_EMAIL_BOOST, 100)

    return match_score, hiring_prob


def score_lead(row: dict) -> tuple[int, int, str]:
    scoring = scoring_fields_from_row(row)
    category, match_score = classify_agency(
        services=scoring.get("services", ""),
        description=scoring.get("description", ""),
        expertise=scoring.get("expertise", ""),
        industries=scoring.get("industries", ""),
    )
    hiring_prob = compute_hiring_probability(
        description=scoring.get("description", ""),
        team_bios=scoring.get("team_bios", ""),
        services=scoring.get("services", ""),
    )
    if hiring_prob >= 40:
        match_score = min(match_score + 5, 100)

    match_score, hiring_prob = _apply_usa_owner_boosts(match_score, hiring_prob, scoring)
    return match_score, hiring_prob, category
