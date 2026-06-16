"""app.py - BharosaCare (Workstream D, Milestone 5).

Two tabs:
  - Find care: pincode + specialty -> ranked, trust-badged results (deterministic
    ranking + trust from core.py), per-card narration (explainer.py), and a Genie
    analytical Q&A box (genie_box.py).
  - My shortlist: facilities the user saved (written to Lakebase via db.py), shown
    on a map.

This page only DISPLAYS what core returns - it never computes distance or trust.
"""

import html
import re
from uuid import uuid4

import pandas as pd
import streamlit as st

import core
import db
import explainer
import genie_box

SPECIALTIES = [
    "Cardiology", "Oncology", "Orthopedics", "Pediatrics",
    "General", "Neurology", "Gynecology",
]
RADIUS_KM = 50

BADGES = {
    "verified":   ("Verified",   "\u2713", "#1a7f37", "#e6f4ea"),
    "partial":    ("Partial",    "\u25d0", "#9a6700", "#fff8c5"),
    "unverified": ("Unverified", "\u25cb", "#57606a", "#eaeef2"),
}

BADGE_HELP = {
    "verified": ("We corroborated this facility's location and that its record lists this "
                 "specialty. Verified means we found supporting evidence \u2014 it is not a "
                 "quality or endorsement rating."),
    "partial": ("Some details checked out, but key fields could not be corroborated from the "
                "source. Worth a closer look before relying on it."),
    "unverified": ("We could not corroborate these details against the facility's source. This "
                   "means missing evidence \u2014 not that the facility is poor quality."),
}

st.set_page_config(page_title="BharosaCare", page_icon="\U0001fa7a", layout="centered")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid4())
session_id = st.session_state.session_id


def badge_html(band: str) -> str:
    label, icon, fg, bg = BADGES.get(band, BADGES["unverified"])
    help_text = html.escape(BADGE_HELP.get(band, BADGE_HELP["unverified"]), quote=True)
    return (
        f"<span title='{help_text}' style='display:inline-block;padding:3px 12px;"
        f"border-radius:999px;background:{bg};color:{fg};font-weight:600;"
        f"font-size:0.85rem;cursor:help;'>{icon}&nbsp;{label}</span>"
    )


def rating_explanation(verdict: dict, f: dict) -> str:
    """Plain-language reason for the band - honest about WHY, including the
    location cross-check that gates 'Verified' independently of the score."""
    band = verdict["band"]
    score = verdict["score"]
    geo = f.get("geo_status") or "unknown"
    has_source = core._is_populated(f.get("source_urls"))
    geo_ok = geo in ("consistent", "repaired")

    if band == "verified":
        return ("We rate this **Verified**: it has a published source and its location checks out "
                "against its pincode. The basics are corroborated \u2014 this is not a quality score.")
    if band == "unverified":
        if not has_source:
            return ("We rate this **Unverified**: we couldn't find a published source to back up "
                    "its listing. That's a gap in the record \u2014 not a judgement on the facility.")
        return ("We rate this **Unverified**: too little of its record could be corroborated. "
                "That's about missing information, not the facility's quality.")
    # Partial: name the real gate, especially a complete record held back by geo.
    if score >= 70 and not geo_ok:
        if geo == "mismatch":
            return ("We rate this **Partial**: the record itself is complete, but its stated "
                    "location **conflicts** with its pincode, so we can't confirm where it "
                    "actually is. A strong record alone doesn't earn Verified without a location "
                    "we can corroborate.")
        return ("We rate this **Partial**: the record is complete, but we **couldn't cross-check "
                "its location** against its pincode. Verified needs both a strong record and a "
                "confirmed location \u2014 so even a perfect evidence score caps at Partial here.")
    return ("We rate this **Partial**: there's some supporting evidence, but not enough to fully "
            "corroborate it. Use it as a starting point and confirm the details before relying on it.")


def best_source(f: dict) -> str | None:
    urls = [u.strip() for u in str(f.get("source_urls") or "").split(";") if u.strip()]
    return urls[0] if urls else None


def directions_url(f: dict) -> str | None:
    lat, lon = f.get("latitude"), f.get("longitude")
    if lat is None or lon is None:
        return None
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"


def clean_explanation(text: str) -> str:
    """Drop a leading conversational question the model sometimes prepends
    (e.g. 'Would you like ...?'). Our summaries never start with a question,
    so if the FIRST sentence is one and real content follows, cut it. Anything
    that opens with a normal statement (ending in '.') is left untouched."""
    text = (text or "").strip()
    m = re.match(r"^[^.?!]*\?\s+(.*)", text, re.DOTALL)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return text


def render_card(f: dict, specialty: str) -> None:
    verdict = core.trust_score(f)          # deterministic - the page does not decide
    why = explainer.explain(f, specialty)  # narration only

    with st.container(border=True):
        st.markdown(badge_html(verdict["band"]), unsafe_allow_html=True)
        st.markdown(
            f"<h4 style='margin:0.3rem 0 0.1rem 0;'>"
            f"{html.escape(f.get('name', 'Unnamed facility'))}</h4>",
            unsafe_allow_html=True,
        )
        st.write(f"\U0001f4cd {f['distance_km']:.1f} km away \u00b7 {f.get('city', '')}")

        facts = []
        if core._is_populated(f.get("number_doctors")):
            facts.append(f"Doctors listed: {f['number_doctors']}")
        if core._is_populated(f.get("capacity")):
            facts.append(f"Beds: {f['capacity']}")
        if facts:
            st.caption(" \u00b7 ".join(facts)
                       + " \u2014 self-reported, shown for context (not part of the trust score)")

        st.write(clean_explanation(why["text"]))
        src = best_source(f)
        if src:
            st.markdown(f"[View source \u2197]({src})")

        st.caption(f"Evidence score: {verdict['score']}/100")
        with st.expander("Why this rating?"):
            st.markdown(rating_explanation(verdict, f))
            st.markdown("**Where the score comes from**")
            for comp in verdict["components"]:
                got, mx = comp["got"], comp["max"]
                mark = "\u2713" if got >= mx - 0.05 else ("\u25d0" if got > 0 else "\u2014")
                st.markdown(f"- {mark} {comp['label']} \u2014 {got:g} of {mx}")
            if f.get("pmjay_match") == "matched":
                st.markdown("- \u2713 PMJAY empanelment \u2014 +5 bonus")

        col_save, col_dir = st.columns(2)
        with col_save:
            if st.button("Save to shortlist", key=f"save_{f['facility_id']}"):
                db.save_facility(session_id, f["facility_id"])
                st.toast("Saved to your shortlist")
        with col_dir:
            gmaps = directions_url(f)
            if gmaps:
                st.markdown(f"[\U0001f9ed Get directions \u2197]({gmaps})")


# --- styling + header ------------------------------------------------------
st.markdown(
    """
    <style>
      /* Banner - the one signature element, in the brand teal */
      .bc-banner {
        background: linear-gradient(135deg, #0f766e 0%, #0b5b54 100%);
        color: #ffffff; padding: 22px 26px; border-radius: 14px; margin-bottom: 18px;
        box-shadow: 0 2px 12px rgba(15, 118, 110, 0.20);
      }
      .bc-banner h1 { color:#fff; margin:0; font-size:1.95rem; font-weight:800;
                      letter-spacing:-0.01em; }
      .bc-banner p  { color:#d7ece9; margin:6px 0 0 0; font-size:1.03rem; }
      .bc-mark { display:inline-flex; align-items:center; justify-content:center;
                 width:30px; height:30px; border-radius:50%;
                 background:rgba(255,255,255,0.18); font-size:1.0rem;
                 margin-right:10px; vertical-align:middle; }
      /* Bigger, clearer tabs */
      .stTabs [data-baseweb="tab-list"] { gap: 8px; }
      .stTabs [data-baseweb="tab"] { font-size: 1.1rem; font-weight: 600; padding: 12px 22px; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    """
    <div class="bc-banner">
      <h1><span class="bc-mark">\u2713</span>BharosaCare</h1>
      <p>Find care you can trust, near any pincode.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_find, tab_saved = st.tabs(["Find care", "My shortlist"])

with tab_find:
    pincode = st.text_input("Pincode", placeholder="e.g. 110001", max_chars=6)
    specialty = st.selectbox("Care needed", SPECIALTIES)

    if st.button("Find care", type="primary"):
        st.session_state.pop("results", None)
        st.session_state.pop("genie_answer", None)
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

            # --- Ask about these facilities (Genie) - placed up here so it's
            #     visible right after a search, not buried under the cards.
            with st.expander("\U0001f4ac Ask about these facilities", expanded=False):
                st.caption(
                    "Natural-language questions about the facility data \u2014 e.g. "
                    "\u201cwhich has the most doctors?\u201d or \u201cwhich is closest?\u201d"
                )
                question = st.text_input(
                    "Your question", key="genie_q",
                    placeholder="e.g. which of these has the most doctors?",
                )
                if st.button("Ask", key="genie_ask") and question.strip():
                    ctx = (f"Context: healthcare facilities near {results['origin']['district']} "
                           f"that offer {results['specialty'].lower()}.")
                    with st.spinner("Asking\u2026"):
                        st.session_state["genie_answer"] = genie_box.ask(question.strip(), context=ctx)
                if "genie_answer" in st.session_state:
                    answer = st.session_state["genie_answer"]
                    if answer:
                        st.info(answer)
                    else:
                        st.caption(
                            "Couldn't answer that one \u2014 try rephrasing it as a data question "
                            "(counts, distances, or which has the most/least of something)."
                        )

            st.divider()
            for f in ranked:
                render_card(f, results["specialty"])

with tab_saved:
    saved = db.list_saved(session_id)
    if not saved:
        st.info("No saved facilities yet. Save some from the **Find care** tab and they'll appear here on a map.")
    else:
        st.write(f"You've saved {len(saved)} facilit{'y' if len(saved) == 1 else 'ies'}.")

        coords = [
            {"latitude": s["latitude"], "longitude": s["longitude"]}
            for s in saved
            if s.get("latitude") is not None and s.get("longitude") is not None
        ]
        if coords:
            st.map(pd.DataFrame(coords))
        else:
            st.caption("Saved facilities have no coordinates to map.")

        st.markdown("### Saved facilities")
        for s in saved:
            name = s.get("name", s["facility_id"])
            city = s.get("city", "")
            st.markdown(f"**{name}**" + (f" \u00b7 {city}" if city else ""))
            d = directions_url(s)
            if d:
                st.markdown(f"[\U0001f9ed Get directions \u2197]({d})")
