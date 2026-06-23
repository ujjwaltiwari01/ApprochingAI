"""Analytics page — database scale and cache coverage.

Cache coverage ≈ website_cache rows / leads — higher means more sites have pre-scraped context.
"""

import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from streamlit_app.db_utils import _count, test_connection

st.set_page_config(page_title="Analytics", layout="wide")
st.title("Analytics")

try:
    conn = test_connection()
    total_leads = conn["leads"]
    cache_count = conn["cache"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Leads", f"{total_leads:,}")
    col2.metric("Cache Entries", f"{cache_count:,}")
    cache_hit_rate = (cache_count / total_leads * 100) if total_leads else 0  # Rough coverage proxy
    col3.metric("Cache Coverage", f"{cache_hit_rate:.1f}%")

    st.subheader("Lead Status")
    new_count = _count("leads", "status=eq.NEW")
    st.bar_chart({"NEW": new_count, "TOTAL": total_leads})
except Exception as exc:
    st.error(f"Error: {exc}")
