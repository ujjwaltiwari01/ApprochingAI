from src.utils.agency_analysis import agency_analysis_from_csv_raw, merge_analysis


def test_usa_csv_analysis_has_summary():
    raw = {
        "Name": "Glenn",
        "email": "glenn@homewatchmarketing.com",
        "Company Name for Emails": "Home Watch Marketing",
        "Industry": "marketing & advertising",
        "Keywords": "property monitoring, home watch, inspection reports",
        "SEO Description": "Home watch marketing helps property managers grow with digital campaigns.",
        "Title": "Marketing Director",
        "Seniority": "Director",
    }
    analysis = agency_analysis_from_csv_raw(raw)
    assert analysis["summary"]
    assert "property" in analysis["summary"].lower() or "home watch" in analysis["summary"].lower()
    assert analysis["industry"] == "marketing & advertising"
    assert "property monitoring" in ", ".join(analysis["services"])


def test_merge_fills_empty_cache_summary():
    cache = {"industry": "tech", "summary": "", "services": []}
    csv = agency_analysis_from_csv_raw(
        {"Description": "We build AI apps", "Services": "web development, AI", "Industries": "tech"},
    )
    merged = merge_analysis(cache, csv)
    assert merged["summary"]
