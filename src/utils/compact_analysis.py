"""Trim agency analysis payloads to cut LLM token usage on free tiers.

Gated by LLM_COMPACT_ANALYSIS in config. Truncation is intentional lossy
compression — we keep fields the personalization prompt needs and drop tail
noise that does not change email quality but does burn rate limits.
"""


def compact_agency_analysis(analysis: dict, max_summary: int = 600) -> dict:
    services = analysis.get("services") or []
    # Some cache rows store services as a comma string; normalize before slicing.
    if isinstance(services, str):
        services = [s.strip() for s in services.split(",") if s.strip()]

    # Same priority order as agency_analysis summary fallback for consistency.
    summary = (
        analysis.get("summary")
        or analysis.get("positioning")
        or analysis.get("specialization")
        or ""
    )

    # Per-field caps mirror typical prompt section sizes; [:8] services is enough context.
    return {
        "industry": (analysis.get("industry") or "")[:120],
        "specialization": (analysis.get("specialization") or "")[:200],
        "positioning": (analysis.get("positioning") or "")[:200],
        "services": [str(s)[:80] for s in services[:8]],
        "hiring_probability": analysis.get("hiring_probability", 0),
        "summary": str(summary)[:max_summary],
    }
