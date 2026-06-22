import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import httpx
from streamlit_app.db_utils import _headers, _url

st.set_page_config(page_title="Campaigns", layout="wide")
st.title("Campaigns")

try:
    today = date.today().isoformat()
    r = httpx.get(
        f"{_url()}/rest/v1/daily_send_counters?send_date=eq.{today}",
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    counters = r.json()

    total_new = sum(c.get("new_sent", 0) for c in counters)
    total_followup = sum(c.get("followup_sent", 0) for c in counters)

    col1, col2, col3 = st.columns(3)
    col1.metric("New Emails Today", total_new)
    col2.metric("Follow-ups Today", total_followup)
    col3.metric("Total Today", total_new + total_followup)

    st.subheader("Per-Account Breakdown")
    if counters:
        st.dataframe(pd.DataFrame(counters), use_container_width=True)
    else:
        st.info("No sends recorded today.")
except Exception as exc:
    st.error(f"Error: {exc}")
