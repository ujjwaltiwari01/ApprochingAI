"""Settings page — env visibility, capacity docs, manual job trigger, webhook URLs.

Does not edit secrets; shows which vars are set and can POST to Render outreach API.
"""

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from streamlit_app.db_utils import test_connection

st.set_page_config(page_title="Settings", layout="wide")
st.title("Settings")

st.subheader("Connection Test")
try:
    result = test_connection()
    st.success(f"Supabase connected — {result['leads']:,} leads, {result['cache']:,} cache entries")
except Exception as exc:
    st.error(f"Connection failed: {exc}")

st.subheader("Environment")
# Boolean only — never render secret values in the UI
st.code(f"DATABASE_URL: {'set' if os.getenv('DATABASE_URL') else 'NOT SET'}")
st.code(f"SUPABASE_URL: {os.getenv('SUPABASE_URL', 'NOT SET')}")
st.code(f"MISTRAL_API_KEY: {'set' if os.getenv('MISTRAL_API_KEY') else 'NOT SET'}")
st.code(f"MISTRAL_API_KEY_2: {'set' if os.getenv('MISTRAL_API_KEY_2') else 'NOT SET'}")
st.code(f"LLM_PROVIDERS: {os.getenv('LLM_PROVIDERS', 'mistral,cerebras,openrouter,gemini,groq')}")

st.subheader("Daily capacity (free tier optimized)")
st.markdown("""
| Resource | Limit |
|----------|-------|
| New emails / day | 450 (150 × 3 Brevo accounts) |
| Follow-ups / day | 450 (150 × 3 Brevo accounts) |
| **Total sends** | **900** |
| LLM provider order | Mistral (2 keys) → Cerebras → OpenRouter → Gemini → Groq |
| LLM timeout | 30s per provider |
| Email validation retries | 1 (saves tokens) |
| Analysis payload | Compact mode ON (fewer tokens) |
""")

st.subheader("Manual Job Trigger")
render_url = os.getenv("RENDER_PUBLIC_URL", "").strip().rstrip("/")
if render_url and not render_url.startswith(("http://", "https://")):
    render_url = f"https://{render_url}"
if not render_url:
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
job_secret = os.getenv("JOB_SECRET", "")

if render_url and job_secret:
    st.caption(
        "Runs **one chunk** (~15 leads). On Render free tier this often takes **3–8 minutes**. "
        "Use GitHub Actions for the full daily run."
    )
    if st.button("Trigger one outreach chunk"):
        import httpx

        base = render_url.rstrip("/")
        with st.spinner("Waking API and processing chunk — please wait (up to 8 min)..."):
            try:
                httpx.get(f"{base}/health", timeout=120)  # Cold-start wake on free tier
                response = httpx.post(
                    f"{base}/jobs/daily-outreach",
                    headers={"Authorization": f"Bearer {job_secret}"},
                    timeout=600,
                )
                response.raise_for_status()
                st.success("Chunk finished")
                st.json(response.json())
            except httpx.TimeoutException:
                st.error(
                    "Timed out after 10 minutes. The job may still be running on Render — "
                    "check outreach-api → Logs, or use GitHub Actions."
                )
            except Exception as exc:
                st.error(f"Failed: {exc}")
else:
    st.info("Set RENDER_PUBLIC_URL and JOB_SECRET to trigger jobs from here.")

st.subheader("Webhook URLs")
base = render_url or "https://your-app.onrender.com"
secret = os.getenv("WEBHOOK_SECRET", "")
# Brevo transactional + inbound reply webhooks (configure in Brevo dashboard)
suffix = f"?secret={secret}" if secret and secret != "change-me-to-random-secret" else ""
st.code(f"Transactional: {base}/webhooks/brevo/transactional{suffix}")
st.code(f"Inbound replies: {base}/webhooks/brevo/inbound{suffix}")
