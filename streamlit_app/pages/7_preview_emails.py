"""Email Preview page — UI wrapper around scripts.preview_emails.generate_previews.

Same LLM pipeline as CLI preview; writes markdown locally and renders it in-browser.
No Brevo send — safe for prompt tuning before production.
"""

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

st.set_page_config(page_title="Email Preview", layout="wide")
st.title("Email Preview (No Send)")

st.markdown(
    "Generate and review outreach copies for **real leads** using the current prompt. "
    "Nothing is sent to Brevo."
)

count = st.slider("Number of leads", 1, 10, 3)
min_score = st.slider("Minimum match score", 70, 100, 85)
include_followup = st.checkbox("Include follow-up #1 preview", value=False)

if st.button("Generate previews", type="primary"):
    with st.spinner("Generating emails via LLM (may take 30–60 seconds)..."):
        try:
            from src.core.config import get_settings

            get_settings.cache_clear()  # Pick up Render env vars on each button click
            s = get_settings()
            missing = [
                # Warn early if primary LLM keys missing on dashboard host
                name
                for name, val in (
                    ("MISTRAL_API_KEY", s.mistral_api_key),
                    ("MISTRAL_API_KEY_2", s.mistral_api_key_2),
                    ("CEREBRAS_API_KEY", s.cerebras_api_key),
                )
                if not (val and val.strip())
            ]
            if missing:
                st.warning(
                    "Missing on this service: "
                    + ", ".join(missing)
                    + ". Add them under outreach-dashboard → Environment on Render."
                )

            from scripts.preview_emails import generate_previews

            out_path = __import__("asyncio").run(  # Streamlit is sync; preview core is async
                generate_previews(count, min_score, include_followup)
            )
            content = out_path.read_text(encoding="utf-8")
            st.success(f"Saved to `{out_path.name}`")
            st.markdown(content)
        except Exception as exc:
            st.error(f"Failed: {exc}")

st.divider()
st.caption("Or run from terminal: `python scripts/preview_emails.py -n 5`")
