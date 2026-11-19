"""Business dashboard: turns the audit trail into numbers a revenue-cycle manager cares about."""
import os
from collections import Counter

import pandas as pd
import requests
import streamlit as st

from app.claims import scrub
from app.rules import describe

API_URL = os.environ.get("CODER_API_URL", "http://localhost:8001")

st.set_page_config(page_title="Coding Dashboard", page_icon="📊", layout="wide")
st.title("📊 AI Coding Performance Dashboard")
st.caption("Computed live from the audit trail. Demo data only.")

try:
    reviews = requests.get(f"{API_URL}/reviews", params={"limit": 10000}, timeout=10).json()
except Exception:
    st.error(f"Cannot reach the API at {API_URL}. Start it first.")
    st.stop()

if not reviews:
    st.info("No approved reviews yet. Approve some cases in the workstation first.")
    st.stop()

# keep only the latest approval per case (re-approvals are corrections)
latest = {}
for r in sorted(reviews, key=lambda r: r["id"]):
    latest[r["case_id"]] = r
df = pd.DataFrame(latest.values())

df["n_suggested"] = df["ai_suggested"].str.len()
df["n_removed"] = df["removed_by_coder"].str.len()
df["n_added"] = df["added_by_coder"].str.len()
df["n_kept"] = df["n_suggested"] - df["n_removed"]
df["unchanged"] = (df["n_removed"] == 0) & (df["n_added"] == 0)
df["fast_unchanged"] = df["unchanged"] & (df["review_seconds"].fillna(999) < 10)
df["claim_blocked"] = df.apply(lambda r: bool(scrub(r.to_dict())), axis=1)

kept, suggested, added = df["n_kept"].sum(), df["n_suggested"].sum(), df["n_added"].sum()
precision = kept / suggested if suggested else 0
recall = kept / (kept + added) if kept + added else 0

# ---------- 1. headline numbers ----------
st.subheader("Overview")
c = st.columns(5)
c[0].metric("Cases coded", len(df))
c[1].metric("AI precision (kept ÷ suggested)", f"{precision:.0%}")
c[2].metric("AI recall (kept ÷ kept + added)", f"{recall:.0%}")
c[3].metric("Avg review time", f"{df['review_seconds'].mean():.0f} s")
c[4].metric("Claims blocked by scrubber", int(df["claim_blocked"].sum()))
st.caption("Precision and recall here are measured against coder decisions in real use, "
           "not against the benchmark test set.")

# ---------- 2. business value (clearly labelled assumptions) ----------
st.subheader("Estimated time saved")
manual_minutes = st.slider("Assumption: minutes to code one case manually, without AI", 2, 30, 8)
assisted_minutes = df["review_seconds"].fillna(0).mean() / 60
saved_hours = (manual_minutes - assisted_minutes) * len(df) / 60
b = st.columns(3)
b[0].metric("Manual (assumed)", f"{manual_minutes} min/case")
b[1].metric("With AI (measured)", f"{assisted_minutes:.1f} min/case")
b[2].metric("Time saved so far", f"{saved_hours:.1f} hours")
st.caption("The manual time is an assumption you set; replace it with a measured baseline before quoting savings.")

# ---------- 3. where the AI is wrong (input for retraining) ----------
st.subheader("Where the AI needs to improve")
left, right = st.columns(2)
with left:
    st.markdown("**Most removed codes** (AI suggested, coder rejected)")
    removed = Counter(c for codes in df["removed_by_coder"] for c in codes).most_common(8)
    st.dataframe(pd.DataFrame([(c, describe(c), n) for c, n in removed],
                              columns=["Code", "Description", "Times removed"]),
                 hide_index=True, width="stretch")
with right:
    st.markdown("**Most added codes** (AI missed, coder added)")
    added_c = Counter(c for codes in df["added_by_coder"] for c in codes).most_common(8)
    st.dataframe(pd.DataFrame([(c, describe(c), n) for c, n in added_c],
                              columns=["Code", "Description", "Times added"]),
                 hide_index=True, width="stretch")

# ---------- 4. coder behaviour (automation-bias monitoring) ----------
st.subheader("Coder review quality")
per_coder = df.groupby("coder").agg(
    cases=("case_id", "count"),
    avg_review_s=("review_seconds", "mean"),
    unchanged_rate=("unchanged", "mean"),
    fast_unchanged=("fast_unchanged", "sum"),
).reset_index()
per_coder["avg_review_s"] = per_coder["avg_review_s"].round(0)
per_coder["unchanged_rate"] = (per_coder["unchanged_rate"] * 100).round(0).astype(int).astype(str) + "%"
st.dataframe(per_coder.rename(columns={
    "coder": "Coder", "cases": "Cases", "avg_review_s": "Avg review (s)",
    "unchanged_rate": "Approved unchanged", "fast_unchanged": "Unchanged in <10 s"}),
    hide_index=True, width="stretch")
st.caption("A high 'approved unchanged' rate, especially with very short review times, can signal "
           "rubber-stamping (automation bias). It needs a supervisor's attention, not automatic blame.")

# ---------- 5. by model version ----------
st.subheader("By model version")
by_model = df.groupby("model_version").agg(cases=("case_id", "count"),
                                           kept=("n_kept", "sum"), suggested=("n_suggested", "sum"),
                                           added=("n_added", "sum")).reset_index()
by_model["precision"] = (by_model["kept"] / by_model["suggested"]).map("{:.0%}".format)
by_model["recall"] = (by_model["kept"] / (by_model["kept"] + by_model["added"])).map("{:.0%}".format)
st.dataframe(by_model[["model_version", "cases", "precision", "recall"]], hide_index=True,
             width="stretch")