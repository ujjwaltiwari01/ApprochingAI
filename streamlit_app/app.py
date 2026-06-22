import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(
    page_title="Job Outreach Dashboard",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.title("Job Outreach")
st.sidebar.markdown("AI-Powered Hyper-Personalized Outreach")

# Connection status in sidebar
try:
    from streamlit_app.db_utils import test_connection

    conn = test_connection()
    st.sidebar.success(f"Supabase connected — {conn['leads']:,} leads")
except Exception as exc:
    st.sidebar.error(f"DB not connected: {exc}")

st.markdown("# Job Outreach Automation")
st.markdown("Select a page from the sidebar to get started.")
