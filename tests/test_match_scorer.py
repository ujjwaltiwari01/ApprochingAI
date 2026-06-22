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


def test_hiring_probability():
    prob = compute_hiring_probability(
        description="We are hiring AI engineers and growing our team",
        team_bios="",
        services="AI Development",
    )
    assert prob >= 40
