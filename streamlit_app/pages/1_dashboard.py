import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from streamlit_app.db_utils import get_dashboard_metrics

st.set_page_config(page_title="Dashboard", layout="wide")
st.title("Dashboard")

try:
    m = get_dashboard_metrics()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.info("Ensure DATABASE_URL is set in .env and restart Streamlit.")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Leads", f"{m['total']:,}")
col2.metric("Emails Sent", f"{m['sent']:,}")
col3.metric("Replies", f"{m['replied']:,}")
col4.metric("Interviews", m["interviews"])

col5, col6, col7, col8 = st.columns(4)
open_rate = (m["opened"] / m["sent"] * 100) if m["sent"] else 0
click_rate = (m["clicked"] / m["sent"] * 100) if m["sent"] else 0
reply_rate = (m["replied"] / m["sent"] * 100) if m["sent"] else 0

col5.metric("Open Rate", f"{open_rate:.1f}%")
col6.metric("Click Rate", f"{click_rate:.1f}%")
col7.metric("Reply Rate", f"{reply_rate:.1f}%")
col8.metric("Hires", m["hired"])

st.divider()
st.subheader("Pipeline Overview")
st.bar_chart({"NEW": m["total"], "SENT": m["sent"], "REPLIED": m["replied"]})
