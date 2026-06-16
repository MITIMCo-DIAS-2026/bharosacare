"""explainer.py - Genie-backed cited explanation, with a templated fallback.

Contract is UNCHANGED, so app.py needs no edit:
    explain(facility, specialty) -> {"text": str, "citations": list[str], "grounded": bool}

What it does:
  - Asks the Genie space (GENIE_SPACE_ID) for a short, plain-language "why this
    facility may or may not suit the specialty," grounded in the facility's own
    record. On success -> grounded=True, text from Genie, citations = the
    facility's source_urls.
  - On ANY problem (no space configured, rate limit, timeout, error, empty
    answer, or budget exhausted) -> a templated grounded=False summary built
    from the facility's own fields, so a card ALWAYS renders. app.py shows the
    "Auto-summary - model unavailable" caption when grounded is False.

Why the guardrails matter (Genie on Free Edition is ~5 questions/min and each
call runs SQL on a warehouse):
  - _cache: keyed by (facility_id, specialty). Streamlit re-runs the whole
    script on every interaction (e.g. each "Save" click), which would otherwise
    re-call Genie for every visible card every time. The cache makes each unique
    facility cost at most one Genie call for the life of the process.
  - MAX_GENIE_CALLS: a process-wide budget so one big search can't blow the rate
    limit. Beyond it, cards fall back to the template. Set MAX_GENIE_CALLS=0 for
    a templates-only demo (instant, no warehouse, no rate limit) - a good, safe
    default if Genie is flaky during judging.
  - GENIE_TIMEOUT_S: per-call timeout so a slow Genie response can't hang a card.

Config (set in app.yaml; all optional except the space id):
    GENIE_SPACE_ID    the Genie space to query (also attach it as an app
                      resource so the service principal gets CAN RUN)
    MAX_GENIE_CALLS   live Genie calls per process (default 3; "0" = templates only)
    GENIE_TIMEOUT_S   seconds to wait per Genie call (default 30)
"""

from __future__ import annotations

import os
from datetime import timedelta

GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID")
MAX_GENIE_CALLS = int(os.environ.get("MAX_GENIE_CALLS", "3"))
GENIE_TIMEOUT = timedelta(seconds=int(os.environ.get("GENIE_TIMEOUT_S", "30")))

# Process-wide state. Fine for a single-process app; not meant to be durable.
_cache: dict[tuple, dict] = {}
_calls_made = 0
_w = None  # lazy WorkspaceClient


def _client():
    global _w
    if _w is None:
        from databricks.sdk import WorkspaceClient
        _w = WorkspaceClient()
    return _w


def _citations(facility: dict) -> list[str]:
    return [u.strip() for u in str(facility.get("source_urls") or "").split(";") if u.strip()]


def _templated(facility: dict, specialty: str) -> dict:
    """Honest, grounded-in-the-row fallback. Identical spirit to the old stub."""
    name = facility.get("name", "This facility")
    has_evidence = bool(facility.get("capability") or facility.get("procedure"))
    if has_evidence:
        text = (f"{name} lists {specialty.lower()} among its services. "
                f"See the linked source to confirm details before visiting.")
    else:
        text = (f"{name} appears in the directory for {specialty.lower()}, but the "
                f"available record is thin. Check the linked source before relying on it.")
    return {"text": text, "citations": _citations(facility), "grounded": False}

def _ask_genie(facility: dict, specialty: str) -> str | None:
    """Return Genie's plain-language answer text, or None if it produced none."""
    name = facility.get("name", "")
    city = facility.get("city", "")
    
    # Build a data summary from the facility dict
    data_points = []
    if facility.get("description"):
        data_points.append(f"Description: {facility['description']}")
    if facility.get("specialties"):
        data_points.append(f"Specialties listed: {facility['specialties']}")
    if facility.get("capability"):
        data_points.append(f"Capabilities: {facility['capability']}")
    if facility.get("procedure"):
        data_points.append(f"Procedures: {facility['procedure']}")
    
    facility_data = "\n".join(data_points) if data_points else "Limited information available"
    
    question = (
        f"Here is information about a healthcare facility:\n\n"
        f"Facility: {name} in {city}\n"
        f"{facility_data}\n\n"
        f"Based ONLY on this information, explain in 2-3 plain sentences whether "
        f"this facility may be suitable for {specialty}. If the information is thin "
        f"or doesn't clearly support {specialty}, say so plainly."
    )
    
    resp = _client().genie.start_conversation_and_wait(
        space_id=GENIE_SPACE_ID,
        content=question,
        timeout=GENIE_TIMEOUT,
    )
    parts = []
    for a in (getattr(resp, "attachments", None) or []):
        text_att = getattr(a, "text", None)
        if text_att and getattr(text_att, "content", None):
            parts.append(text_att.content.strip())
    answer = " ".join(p for p in parts if p)
    return answer or None


def explain(facility: dict, specialty: str) -> dict:
    global _calls_made

    key = (facility.get("facility_id"), specialty)
    if key in _cache:
        return _cache[key]

    # No space configured, or we've spent our Genie budget -> template.
    if not GENIE_SPACE_ID or GENIE_SPACE_ID == "PASTE_YOUR_GENIE_SPACE_ID":
        print("[explainer] GENIE_SPACE_ID is not set (still placeholder/empty) -> templating")
        result = _templated(facility, specialty)
        _cache[key] = result
        return result
    if _calls_made >= MAX_GENIE_CALLS:
        print(f"[explainer] Genie budget spent (MAX_GENIE_CALLS={MAX_GENIE_CALLS}) -> templating")
        result = _templated(facility, specialty)
        _cache[key] = result
        return result

    try:
        answer = _ask_genie(facility, specialty)
        if answer:
            _calls_made += 1  # count only SUCCESSFUL Genie answers toward the budget
            result = {"text": answer, "citations": _citations(facility), "grounded": True}
        else:
            print("[explainer] Genie returned no text attachment -> templating")
            result = _templated(facility, specialty)
    except Exception as e:
        # rate limit, timeout, auth/403, SDK version, anything -> degrade gracefully,
        # but LOG the real reason so it shows in the app's Logs tab.
        print(f"[explainer] Genie call failed -> templating: {type(e).__name__}: {e}")
        result = _templated(facility, specialty)

    _cache[key] = result
    return result