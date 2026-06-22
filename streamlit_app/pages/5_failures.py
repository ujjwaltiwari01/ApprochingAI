import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import httpx
from streamlit_app.db_utils import _headers, _url

st.set_page_config(page_title="Failures", layout="wide")
st.title("Failures & Job Logs")

try:
    r = httpx.get(
        f"{_url()}/rest/v1/jobs?status=in.(failed,running,paused)&order=started_at.desc&limit=50",
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    jobs = r.json()

    if jobs:
        for job in jobs:
            with st.expander(f"Job {job.get('id', '')[:8]}... — {job.get('status')}"):
                st.json(job)
    else:
        st.success("No failed jobs.")
except Exception as exc:
    st.error(f"Error: {exc}")
