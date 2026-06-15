"""app.py - BharosaCare (Workstream D, Milestone 5).

Single mobile-first page: pincode + specialty -> ranked, trust-badged, cited
results. The ranking and the trust verdict come from core.py (deterministic,
golden-tested). This page only DISPLAYS what core returns - it never computes
distance or trust itself. The model (explainer) only narrates.

Wired to the db/explainer STUBS today; when Owner B's db.py and Owner C's
explainer.py land, they replace those files and nothing here changes.
"""

from uuid import uuid4

import streamlit as st

import core
import db
import explainer

# Controlled specialty list (the only thing the user picks, besides pincode).
SPECIALTIES = [
    "Cardiology", "Oncology", "Orthopedics", "Pediatrics",
    "General", "Neurology", "Gynecology",
]
RADIUS_KM = 50

# band -> (label, icon, text colour, background) : word + icon + colour, never colour alone
BADGES = {
    "verified":   ("Verified",   "\u2713", "#1a7f37", "#e6f4ea"),
    "partial":    ("Partial",    "\u25d0", "#9a6700", "#fff8c5"),
    "unverified": ("Unverified", "\u25cb", "#57606a", "#eaeef2"),
}

st.set_page_config(page_title="BharosaCare", page_icon="\U0001fa7a", layout="centered")

# session id stands in for the uuid cookie (Streamlit has no cookie primitive)
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid4())
session_id = st.session_state.session_id


def badge_html(band: str) -> str:
    label, icon, fg, bg = BADGES.get(band, BADGES["unverified"])
    return (
        f"<span style='display:inline-block;padding:3px 12px;border-radius:999px;"
        f"background:{bg};color:{fg};font-weight:600;font-size:0.85rem;'>"
        f"{icon}&nbsp;{label}</span>"
    )


def render_card(f: dict, specialty: str) -> None:
    verdict = core.trust_score(f)          # deterministic - the page does not decide
    why = explainer.explain(f, specialty)  # narration only

    with st.container(border=True):
        st.markdown(badge_html(verdict["band"]), unsafe_allow_html=True)
        st.markdown(f"#### {f.get('name', 'Unnamed facility')}")
        st.write(f"\U0001f4cd {f['distance_km']:.1f} km away \u00b7 {f.get('city', '')}")

        st.write(why["text"])
        if not why["grounded"]:
            st.caption("Auto-summary \u2014 model unavailable")
        for url in why.get("citations", []):
            st.markdown(f"[Open source]({url})")

        if verdict["band"] == "partial":
            st.caption("\u26a0\ufe0f Needs a closer look")
        if verdict["unverified_fields"]:
            missing = ", ".join(x.replace("_", " ") for x in verdict["unverified_fields"])
            st.caption(f"Not stated \u2014 see source: {missing}")

        if st.button("Save to shortlist", key=f"save_{f['facility_id']}"):
            db.save_facility(session_id, f["facility_id"])
            st.toast("Saved to your shortlist")


# --- header ----------------------------------------------------------------
st.title("BharosaCare")
st.caption("Find care you can trust, near any pincode.")

# --- inputs ----------------------------------------------------------------
pincode = st.text_input("Pincode", placeholder="e.g. 110001", max_chars=6)
specialty = st.selectbox("Care needed", SPECIALTIES)

if st.button("Find care", type="primary"):
    st.session_state.pop("results", None)
    if not pincode.strip():
        st.warning("Enter a 6-digit pincode to search.")
    else:
        with st.spinner("Searching nearby facilities\u2026"):
            origin = db.get_pincode(pincode.strip())
        if origin is None:
            st.warning(f"We couldn't find pincode {pincode}. Check the 6 digits and try again.")
        else:
            candidates = db.get_facilities_in_bbox(origin["lat"], origin["lon"], RADIUS_KM)
            ranked = core.rank_facilities(
                origin["lat"], origin["lon"], specialty, candidates,
                radius_km=RADIUS_KM, limit=10,
            )
            st.session_state.results = {"origin": origin, "specialty": specialty, "ranked": ranked}

# --- results (rendered from session_state so saves don't wipe the page) ----
results = st.session_state.get("results")
if results:
    ranked = results["ranked"]
    if not ranked:
        st.info("No facilities within 50 km offer that. Try a different specialty or pincode.")
    else:
        st.write(
            f"We found {len(ranked)} place(s) near {results['origin']['district']} "
            f"that say they offer {results['specialty'].lower()}."
        )
        for f in ranked:
            render_card(f, results["specialty"])

# --- shortlist -------------------------------------------------------------
saved = db.list_saved(session_id)
if saved:
    st.divider()
    st.markdown("### Your shortlist")
    for s in saved:
        st.write(f"\u2022 {s.get('name', s['facility_id'])}")
