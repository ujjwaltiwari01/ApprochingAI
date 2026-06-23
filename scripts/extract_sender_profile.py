"""One-off script: write sender_profile.json for email personalization.

Run manually when updating Ujjwal's bio/skills; EmailGenerator reads
config/sender_profile.json when drafting outreach. Not part of daily cron.
"""

import json
from pathlib import Path

# Static sender persona — injected into LLM prompts as "who is reaching out"
PROFILE = {
    "name": "Ujjwal Tiwari",
    "title": "AI Engineer",
    "location": "Varanasi, India",
    "email": "ujjwal.it2023-24@recabn.ac.in",
    "phone": "+91-93362-69095",
    "portfolio_url": "https://ujjwaltiwari01.netlify.app/",
    "linkedin_url": "https://linkedin.com/in/ujjwal-tiwari-b34044341",
    "github_url": "https://github.com/ujjwaltiwari01",
    "summary": (
        "AI engineer with hands-on experience building and deploying LLM systems, "
        "RAG pipelines, and workflow automation in production environments."
    ),
    "skills": [
        "Generative AI", "LangChain", "OpenAI API", "RAG", "LLM Agents",
        "Python", "FastAPI", "Supabase", "Streamlit", "n8n",
    ],
    "seeking": [
        "AI Engineer roles", "AI Consultant roles", "AI Internships",
        "Contract opportunities", "Agency partnerships",
    ],
}

output = Path(__file__).parent.parent / "config" / "sender_profile.json"
# Consumed by EmailGenerator when building the "about the sender" section of prompts
output.write_text(json.dumps(PROFILE, indent=2), encoding="utf-8")
print(f"Written to {output}")
