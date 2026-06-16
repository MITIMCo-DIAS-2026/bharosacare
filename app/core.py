"""core.py - BharosaCare deterministic engine.

Pure functions only: no network, no I/O, no model calls. The ranking and the
trust verdict are computed HERE, deterministically. The model only narrates.

TRUST MODEL (v2): the score measures how well a listing can be CORROBORATED -
not how big or "good" a facility is. Three honest ideas drive the variance:
  1. Graded credit: present-but-thin fields earn a floor; richer ones earn more
     (more sources, longer capability/procedure/equipment text).
  2. Location confidence is scored, not just gated (geo cross-check + coord
     precision).
  3. Specialty corroboration: a small reward when the narrative text actually
     backs the facility's own listed specialties.
Deliberately NOT a signal: the MAGNITUDE of number_doctors / capacity. A
self-reported headcount is unverified and gameable, and size is not trust - so
those fields count by PRESENCE only, never by how large the number is.

Locked by test_core.py. Do not edit once green.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0

# Sparse fields surfaced honestly when missing ("Not stated - see source").
SPARSE_FIELDS = ["number_doctors", "capacity", "year_established", "equipment"]

# Scoring component max points (sum = 100).
COMPONENT_MAX = {
    "source": 25, "specialties": 10, "capability": 10, "procedure": 10,
    "equipment": 5, "year": 2, "doctors": 1, "capacity": 1,
    "location": 21, "corroboration": 15,
}

_PRESENCE_FLOOR = 0.6        # a present-but-thin graded field still earns this
_SOURCE_FULL_COUNT = 3       # this many distinct sources = full source credit
_TEXT_FULL_CHARS = 80        # narrative chars for full capability/procedure credit
_EQUIP_FULL_CHARS = 40
_GEO_FACTOR = {"consistent": 1.0, "repaired": 0.7, "unknown": 0.4, "mismatch": 0.1}


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
    """Keep facilities offering `specialty`, within radius, nearest first."""
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


# --- graded sub-scores (each returns a fraction in [0, 1]) -----------------

def _present_frac(value) -> float:
    return 1.0 if _is_populated(value) else 0.0


def _graded(value, full_at: float) -> float:
    """Floor for being present, scaling up to 1.0 as richness reaches full_at."""
    if not _is_populated(value):
        return 0.0
    return _PRESENCE_FLOOR + (1 - _PRESENCE_FLOOR) * min(value_richness(value, full_at), 1.0)


def value_richness(value, full_at: float) -> float:
    return len(str(value).strip()) / full_at


def _source_frac(value) -> float:
    if not _is_populated(value):
        return 0.0
    n = len([u for u in str(value).split(";") if u.strip()])
    return _PRESENCE_FLOOR + (1 - _PRESENCE_FLOOR) * min(n / _SOURCE_FULL_COUNT, 1.0)


def _location_frac(facility: dict) -> float:
    geo = facility.get("geo_status") or "unknown"
    g = _GEO_FACTOR.get(geo, 0.4)
    coord = 1.0 if (facility.get("coord_source") == "facility") else 0.6
    return 0.75 * g + 0.25 * coord


def _corroboration_frac(facility: dict) -> float:
    """Fraction of the facility's own specialties whose stem appears in its
    narrative text - i.e. the record substantiates what it claims."""
    specs = _specialties_set(facility.get("specialties"))
    if not specs:
        return 0.0
    narrative = " ".join(
        str(facility.get(k) or "") for k in ("description", "capability", "procedure")
    ).lower()
    if not narrative.strip():
        return 0.0
    hits = sum(1 for s in specs if s[:5] in narrative)
    return hits / len(specs)


def trust_score(facility: dict) -> dict:
    """Deterministic trust verdict (v2 model).

    Returns {score, band, reasons, unverified_fields, components}. Sparse fields
    are never treated as facts; the magnitude of doctor count / capacity is
    never a signal (presence only).
    """
    has_source = _is_populated(facility.get("source_urls"))
    geo_status = facility.get("geo_status") or "unknown"

    fracs = {
        "source": _source_frac(facility.get("source_urls")),
        "specialties": _present_frac(facility.get("specialties")),
        "capability": _graded(facility.get("capability"), _TEXT_FULL_CHARS),
        "procedure": _graded(facility.get("procedure"), _TEXT_FULL_CHARS),
        "equipment": _graded(facility.get("equipment"), _EQUIP_FULL_CHARS),
        "year": _present_frac(facility.get("year_established")),
        "doctors": _present_frac(facility.get("number_doctors")),   # presence only
        "capacity": _present_frac(facility.get("capacity")),        # presence only
        "location": _location_frac(facility),
        "corroboration": _corroboration_frac(facility),
    }

    labels = {
        "source": "Published source", "specialties": "Specialties listed",
        "capability": "Capabilities described", "procedure": "Procedures described",
        "equipment": "Equipment listed", "year": "Year established",
        "doctors": "Doctor count listed", "capacity": "Bed capacity listed",
        "location": "Location confidence", "corroboration": "Specialty corroboration",
    }
    components = [
        {"label": labels[k], "got": round(COMPONENT_MAX[k] * fracs[k], 1),
         "max": COMPONENT_MAX[k]}
        for k in COMPONENT_MAX
    ]
    score = round(sum(c["got"] for c in components))

    pmjay_matched = facility.get("pmjay_match") == "matched"
    if pmjay_matched:
        score = min(100, score + 5)

    # Band: no citable source => unverified. Verified requires a strong score
    # AND a corroborated location (a mismatch can never be consistent/repaired).
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
    if fracs["corroboration"] > 0:
        reasons.append("its description backs the specialties it lists")
    if pmjay_matched:
        reasons.append("corroborated by PMJAY empanelment")

    unverified_fields = [f for f in SPARSE_FIELDS if not _is_populated(facility.get(f))]
    reasons += [f"{f.replace('_', ' ')} not stated" for f in unverified_fields]

    return {
        "score": score,
        "band": band,
        "reasons": reasons,
        "unverified_fields": unverified_fields,
        "components": components,
    }
