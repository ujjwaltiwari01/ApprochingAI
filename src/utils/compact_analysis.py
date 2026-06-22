"""Trim agency analysis payloads to cut LLM token usage on free tiers."""


def compact_agency_analysis(analysis: dict, max_summary: int = 600) -> dict:
    services = analysis.get("services") or []
    if isinstance(services, str):
        services = [s.strip() for s in services.split(",") if s.strip()]

    summary = (
        analysis.get("summary")
        or analysis.get("positioning")
        or analysis.get("specialization")
        or ""
    )

    return {
        "industry": (analysis.get("industry") or "")[:120],
        "specialization": (analysis.get("specialization") or "")[:200],
        "positioning": (analysis.get("positioning") or "")[:200],
        "services": [str(s)[:80] for s in services[:8]],
        "hiring_probability": analysis.get("hiring_probability", 0),
        "summary": str(summary)[:max_summary],
    }
