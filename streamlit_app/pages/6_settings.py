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
    if st.button("Trigger Daily Outreach"):
        import httpx

        try:
            response = httpx.post(
                f"{render_url}/jobs/daily-outreach",
                headers={"Authorization": f"Bearer {job_secret}"},
                timeout=10,
            )
            st.json(response.json())
        except Exception as exc:
            st.error(f"Failed: {exc}")
else:
    st.info("Set RENDER_PUBLIC_URL and JOB_SECRET to trigger jobs from here.")

st.subheader("Webhook URLs")
base = render_url or "https://your-app.onrender.com"
secret = os.getenv("WEBHOOK_SECRET", "")
suffix = f"?secret={secret}" if secret and secret != "change-me-to-random-secret" else ""
st.code(f"Transactional: {base}/webhooks/brevo/transactional{suffix}")
st.code(f"Inbound replies: {base}/webhooks/brevo/inbound{suffix}")
