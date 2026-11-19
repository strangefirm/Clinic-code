"""Coder workstation: a coder reviews the AI's suggestions, then accepts, removes or adds codes."""
import os
import time
import uuid
import requests
import streamlit as st

from app.rules import check_codes

API_URL = os.environ.get("CODER_API_URL", "http://localhost:8001")
HEADERS = {"X-API-Key": os.environ.get("CODER_API_KEY", "")}

DEMO_CASES = {
    "CASE-001 · Diabetes, hypertension, cough": (
        "68-year-old male admitted for poorly controlled type 2 diabetes with hyperglycemia. "
        "History of hypertension. Persistent cough and headache for one week."),
    "CASE-002 · Fever and anemia": (
        "45-year-old woman with fever of 39 C, generalized pain and anemia. "
        "Elevated white blood cell count."),
    "CASE-003 · Back pain and hematuria": (
        "72-year-old man with low back pain for three months and hematuria. "
        "Ultrasound showed a renal cyst. Known smoker, 20 cigarettes per day."),
    "New case (type your own)": "",
}

st.set_page_config(page_title="Coding Workstation", page_icon="🏥", layout="wide")
st.title("🏥 Clinical Coding Workstation")
st.caption("AI-assisted ICD-10-CM coding with human review. Demo only: do not enter real patient data.")

# ---------- sidebar: coder, API status, case queue ----------
with st.sidebar:
    coder = st.text_input("Coder name", value="coder1")
    try:
        h = requests.get(f"{API_URL}/health", timeout=5).json()
        st.success(f"AI service online · {h['model_version']}")
    except Exception:
        st.error(f"AI service offline ({API_URL}). Start the API and Ollama.")
    st.subheader("Recent approvals")
    try:
        for rv in requests.get(f"{API_URL}/reviews", params={"limit": 5}, headers=HEADERS, timeout=5).json():
            st.caption(f"#{rv['id']} · {rv['case_id']} · {rv['coder']} · "
                       f"-{len(rv['removed_by_coder'])} +{len(rv['added_by_coder'])}")
    except Exception:
        st.caption("(not available)")
    st.subheader("Case queue")
    case_label = st.radio("Select a case", list(DEMO_CASES), label_visibility="collapsed")

is_new = not case_label.startswith("CASE-")
if is_new:
    # every new case gets its own unique ID; queued cases keep theirs
    if "new_case_id" not in st.session_state or st.sidebar.button("➕ Start another new case"):
        st.session_state["new_case_id"] = f"NEW-{uuid.uuid4().hex[:6].upper()}"
    case_id = st.session_state["new_case_id"]
else:
    case_id = case_label.split(" ")[0]
st.markdown(f"**Case ID:** `{case_id}`")
note = st.text_area("Clinical note", value=DEMO_CASES[case_label], height=180,
                    key=f"note_{case_id}", disabled=not is_new,
                    help=None if is_new else "Queued case notes are read-only: the note belongs to this case ID.")
state = st.session_state.setdefault("cases", {})

if st.button("🤖 Get AI suggestions", type="primary", disabled=len(note.strip()) < 20):
    with st.spinner("The model is reading the note..."):
        try:
            r = requests.post(f"{API_URL}/suggest", json={"text": note, "case_id": case_id}, headers=HEADERS, timeout=300)
            r.raise_for_status()
            state[case_id] = {"ai": r.json(), "added": [], "shown_at": time.time()}
        except Exception as e:
            st.error(f"Could not get suggestions: {e}")

case = state.get(case_id)
if case:
    ai = case["ai"]
    left, right = st.columns([3, 2])

    with left:
        st.subheader("AI suggestions")
        st.caption(f"Model {ai['model_version']} · {ai['latency_seconds']} s")
        kept = []
        for item in ai["accepted"]:
            if st.checkbox(f"**{item['code']}**: {item['description']}", value=True,
                           key=f"keep_{case_id}_{item['code']}"):
                kept.append(item["code"])
        for f in ai["flagged"]:
            st.warning(f"⚠️ **{f['item']}**: {f['reason']}")
        for rj in ai["rejected"]:
            st.error(f"❌ **{rj['code']}** blocked: {rj['reason']}")

        st.markdown("**Add a missing code**")
        c1, c2 = st.columns([3, 1])
        new_code = c1.text_input("ICD-10-CM code", key=f"new_{case_id}", label_visibility="collapsed",
                                 placeholder="e.g. R52")
        if c2.button("Add", key=f"add_{case_id}") and new_code.strip():
            check = check_codes([new_code])
            if check["accepted"]:
                code = check["accepted"][0]["code"]
                if code not in case["added"] and code not in kept:
                    case["added"].append(code)
            else:
                reason = (check["rejected"] or check["flagged"])[0]["reason"]
                st.error(f"Can't add {new_code.upper()}: {reason}")
        for code in case["added"]:
            st.write(f"➕ **{code}**: {check_codes([code])['accepted'][0]['description']}")

    with right:
        st.subheader("Final coding")
        final = kept + [c for c in case["added"] if c not in kept]
        if not final:
            st.info("No codes selected.")
        else:
            principal = st.selectbox("Principal diagnosis", final, key=f"principal_{case_id}")
            final_check = check_codes(final)
            for f in final_check["flagged"]:
                st.warning(f"⚠️ {f['item']}: {f['reason']}")

            suggested = [a["code"] for a in ai["accepted"]]
            removed = [c for c in suggested if c not in kept]
            m1, m2, m3 = st.columns(3)
            m1.metric("AI kept", f"{len(kept)}/{len(suggested)}")
            m2.metric("Removed", len(removed))
            m3.metric("Added", len(case["added"]))

            if st.button("✅ Approve coding", type="primary", key=f"approve_{case_id}"):
                record = {
                    "case_id": ai["case_id"],
                    "coder": coder,
                    "model_version": ai["model_version"],
                    "note_text": note,
                    "diagnoses": [{"code": c, "type": "Principal" if c == principal else "Secondary"}
                                  for c in [principal] + [c for c in final if c != principal]],
                    "ai_suggested": suggested,
                    "removed_by_coder": removed,
                    "added_by_coder": list(case["added"]),
                    "ai_latency_seconds": ai["latency_seconds"],
                    "review_seconds": round(time.time() - case["shown_at"], 1),
                }
                try:
                    r = requests.post(f"{API_URL}/reviews", json=record, headers=HEADERS, timeout=10)
                    r.raise_for_status()
                    record["review_id"] = r.json()["review_id"]
                    case["approved"] = record
                except Exception as e:
                    st.error(f"Could not save the review: {e}")
            if case.get("approved"):
                rec = case["approved"]
                st.success(f"Saved to audit trail as review #{rec['review_id']} "
                           f"(reviewed in {rec['review_seconds']} s)")
                if not rec["removed_by_coder"] and not rec["added_by_coder"] and rec["review_seconds"] < 10:
                    st.warning("Approved without changes in under 10 seconds. Was every code checked?")
                xml = requests.get(f"{API_URL}/reviews/{rec['review_id']}/claim.xml", headers=HEADERS, timeout=10)
                if xml.ok:
                    st.download_button("📄 Download claim XML", xml.content,
                                       file_name=f"claim_{rec['case_id']}_{rec['review_id']}.xml",
                                       mime="application/xml", key=f"dl_{rec['review_id']}")
                else:
                    detail = xml.json().get("detail", {})
                    st.error("Claim blocked by scrubber: " + "; ".join(detail.get("problems", [str(detail)])))
                with st.expander("Audit record"):
                    st.json(rec)