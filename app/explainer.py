"""explainer.py - STUB (Owner D's wiring stub).

>>> OWNER C: replace this ENTIRE file with the real Agent Bricks client. <<<
Keep this signature EXACTLY so app.py needs no change:
    explain(facility, specialty) -> {"text": str, "citations": list[str], "grounded": bool}

The real version calls the 'bharosacare-explainer' Knowledge Assistant and
returns grounded=True with a cited explanation; on any endpoint error it falls
back to exactly this templated, grounded=False form. This stub always returns
the fallback so the app's degraded state is visible from minute one.
"""


def explain(facility: dict, specialty: str) -> dict:
    name = facility.get("name", "This facility")
    citations = [u for u in str(facility.get("source_urls") or "").split(";") if u.strip()]
    has_evidence = bool(facility.get("capability") or facility.get("procedure"))

    if has_evidence:
        text = (f"{name} lists {specialty.lower()} among its services. "
                f"See the linked source to confirm details before visiting.")
    else:
        text = (f"{name} appears in the directory for {specialty.lower()}, but the "
                f"available record is thin. Check the linked source before relying on it.")

    return {"text": text, "citations": citations, "grounded": False}
