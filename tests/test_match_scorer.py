"""Tests: keyword-based lead scoring — fast O(1) per row vs LLM at import time on 67k leads."""
from src.services.match_scorer import classify_agency, compute_hiring_probability, score_lead


def test_ai_agency_score():
    row = {
        "Services": "AI Development, Machine Learning, Chatbot",
        "Description": "We build AI solutions for enterprise clients",
        "Areas of Expertise": "AI Expertise, NLP",
        "Industries": "Technology",
    }
    score, hiring, category = score_lead(row)
    assert score == 95
    assert category == "ai_agency"


def test_marketing_agency_score():
    row = {
        "Services": "SEO, PPC, Social Media Marketing",
        "Description": "Digital marketing agency",
        "Areas of Expertise": "SEO Expertise",
        "Industries": "eCommerce",
    }
    score, _, category = score_lead(row)
    assert score == 80
    assert category == "marketing"


def test_usa_owner_priority_boost():
    row = {
        "Name": "Jane",
        "Last Name": "Doe",
        "Title": "Marketing Director",
        "Seniority": "Director",
        "email": "jane@acmeagency.com",
        "Company Name for Emails": "Acme Agency",
        "website": "http://www.acmeagency.com",
        "Industry": "marketing & advertising",
        "Keywords": "seo, ppc, digital marketing, branding",
        "SEO Description": "Full-service digital marketing agency",
        "Country": "United States",
    }
    score, hiring, category = score_lead(row)
    assert category == "marketing"
    assert score >= 100 or score >= 93
    assert hiring >= 15


def test_hiring_probability():
    prob = compute_hiring_probability(
        description="We are hiring AI engineers and growing our team",
        team_bios="",
        services="AI Development",
    )
    assert prob >= 40
