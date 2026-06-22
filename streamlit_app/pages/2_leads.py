import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.db.models import LeadStatus
from streamlit_app.db_utils import fetch_leads

st.set_page_config(page_title="Leads", layout="wide")
st.title("Leads")

status_filter = st.selectbox(
    "Filter by status",
    ["All"] + [s.value for s in LeadStatus],
)
score_min = st.slider("Minimum match score", 0, 100, 0)
limit = st.number_input("Max results", 10, 1000, 100)

try:
    leads = fetch_leads(
        status=None if status_filter == "All" else status_filter,
        score_min=score_min,
        limit=int(limit),
    )
    if leads:
        data = [{
            "Company": l.get("company_name"),
            "Email": l.get("email"),
            "Country": l.get("country"),
            "Status": l.get("status"),
            "Match Score": l.get("match_score"),
            "Hiring Prob": l.get("hiring_probability"),
            "Sent": (l.get("sent_at") or "")[:10],
            "Replied": (l.get("replied_at") or "")[:10],
        } for l in leads]
        st.dataframe(pd.DataFrame(data), use_container_width=True)
        st.caption(f"Showing {len(leads)} leads")
    else:
        st.info("No leads found.")
except Exception as exc:
    st.error(f"Error: {exc}")
