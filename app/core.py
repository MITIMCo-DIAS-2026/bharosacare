"""core.py - BharosaCare deterministic engine.

Pure functions only: no network, no I/O, no model calls. The ranking and the
trust verdict are computed HERE, deterministically. The model (explainer.py)
only narrates results this module decides.

Locked by test_core.py (the Appendix golden table). Do not edit once green.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0

# Evidence fields and their weights (Appendix trust-score rubric). Sum = 1.00.
EVIDENCE_WEIGHTS = {
    "source_urls": 0.30,
    "specialties": 0.20,
    "capability": 0.15,
    "procedure": 0.15,
    "equipment": 0.10,
    "year_established": 0.04,
    "number_doctors": 0.03,
    "capacity": 0.03,
}

# Sparse fields surfaced honestly when missing ("Not stated - see source").
SPARSE_FIELDS = ["number_doctors", "capacity", "year_established", "equipment"]


def _is_populated(value) -> bool:
    """A field counts as present only if it is non-null and not blank."""
    if value is None:
        return False
    return str(value).strip() != ""


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in kilometres (R = 6371)."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _specialties_set(raw) -> set:
    """Split a ';'-delimited specialties string into a normalised set."""
    if not _is_populated(raw):
        return set()
    return {s.strip().lower() for s in str(raw).split(";") if s.strip()}


def rank_facilities(origin_lat, origin_lon, specialty, facilities,
                    radius_km: float = 50, limit: int = 10) -> list:
    """Keep facilities offering `specialty`, within radius, nearest first.

    Specialty match is case-insensitive over a ';'-split list (token equality).
    Adds 'distance_km' to each returned facility. Returns at most `limit`.
    """
    wanted = specialty.strip().lower()
    matched = []
    for f in facilities:
        if wanted not in _specialties_set(f.get("specialties")):
            continue
        dist = haversine_km(origin_lat, origin_lon, f["latitude"], f["longitude"])
        if dist > radius_km:
            continue
        out = dict(f)
        out["distance_km"] = dist
        matched.append(out)
    matched.sort(key=lambda f: f["distance_km"])
    return matched[:limit]


def _completeness_score(facility: dict) -> float:
    """Weighted populated-fraction of the evidence fields (0..1)."""
    return sum(w for field, w in EVIDENCE_WEIGHTS.items()
               if _is_populated(facility.get(field)))


def trust_score(facility: dict) -> dict:
    """Deterministic trust verdict per the Appendix rubric.

    Returns {score, band, reasons, unverified_fields}. Never treats a sparse
    field as a fact - missing ones are listed in unverified_fields only.
    """
    has_source = _is_populated(facility.get("source_urls"))
    geo_status = facility.get("geo_status") or "unknown"
    score = round(100 * _completeness_score(facility))

    # (Stretch, feature-flagged in M7) PMJAY corroboration: bonus only, never
    # a penalty. 'not_found' / null change nothing.
    pmjay_matched = facility.get("pmjay_match") == "matched"
    if pmjay_matched:
        score = min(100, score + 5)

    # Band logic. No citable source => unverified, regardless of other fields.
    # A geo mismatch is never in {consistent, repaired}, so it can never reach
    # 'verified' - it is capped at 'partial' at best.
    if not has_source:
        band = "unverified"
    elif score >= 70 and geo_status in ("consistent", "repaired"):
        band = "verified"
    elif score >= 40:
        band = "partial"
    else:
        band = "unverified"

    reasons = ["has a citable source" if has_source else "no citable source found"]
    if geo_status == "consistent":
        reasons.append("facility state matches its pincode")
    elif geo_status == "repaired":
        reasons.append("location filled in from the pincode directory")
    elif geo_status == "mismatch":
        reasons.append("facility state conflicts with its pincode")
    else:
        reasons.append("location could not be cross-checked")
    if pmjay_matched:
        reasons.append("corroborated by PMJAY empanelment")

    unverified_fields = [f for f in SPARSE_FIELDS if not _is_populated(facility.get(f))]
    reasons += [f"{f.replace('_', ' ')} not stated" for f in unverified_fields]

    return {
        "score": score,
        "band": band,
        "reasons": reasons,
        "unverified_fields": unverified_fields,
    }
