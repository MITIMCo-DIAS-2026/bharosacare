"""test_core.py - the Appendix golden table. Core must pass all 10.

Run:  pytest test_core.py      (or)      python test_core.py
"""

from core import haversine_km, rank_facilities, trust_score

KM_PER_DEG = 111.194  # great-circle km per degree of latitude along a meridian


def _full_facility(**overrides):
    """A facility with every evidence field populated; override to test gaps."""
    base = {
        "name": "Test Hospital",
        "latitude": 0.0, "longitude": 0.0,
        "specialties": "cardiology",
        "source_urls": "https://example.gov.in/x",
        "capability": "cardiac care",
        "procedure": "angioplasty",
        "equipment": "cath lab",
        "number_doctors": "12",
        "capacity": "200",
        "year_established": "1992",
        "geo_status": "consistent",
    }
    base.update(overrides)
    return base


# --- haversine -------------------------------------------------------------

def test_1_haversine_one_degree():
    assert abs(haversine_km(0, 0, 1, 0) - 111.19) <= 0.5  # catches deg/rad bug


def test_2_haversine_delhi_mumbai():
    d = haversine_km(28.6139, 77.2090, 19.0760, 72.8777)
    assert abs(d - 1148) <= 15


def test_3_haversine_zero():
    assert haversine_km(12.97, 77.59, 12.97, 77.59) == 0.0


# --- rank_facilities -------------------------------------------------------

def test_4_rank_drops_beyond_radius_and_orders():
    facs = [
        {"name": "A", "specialties": "cardiology", "latitude": 5 / KM_PER_DEG, "longitude": 0},
        {"name": "B", "specialties": "cardiology", "latitude": 20 / KM_PER_DEG, "longitude": 0},
        {"name": "C", "specialties": "cardiology", "latitude": 60 / KM_PER_DEG, "longitude": 0},
    ]
    out = rank_facilities(0, 0, "cardiology", facs, radius_km=50)
    assert len(out) == 2
    assert [f["name"] for f in out] == ["A", "B"]          # 5km then 20km
    assert out[0]["distance_km"] < out[1]["distance_km"]   # ascending
    assert all(f["name"] != "C" for f in out)              # 60km dropped


def test_5_rank_no_specialty_match():
    facs = [{"name": "A", "specialties": "cardiology", "latitude": 0, "longitude": 0}]
    assert rank_facilities(0, 0, "oncology", facs, radius_km=50) == []


def test_6_rank_case_insensitive_semicolon_split():
    facs = [{"name": "A", "specialties": "general;cardiology", "latitude": 0, "longitude": 0}]
    out = rank_facilities(0, 0, "Cardiology", facs, radius_km=50)
    assert len(out) == 1


# --- trust_score -----------------------------------------------------------

def test_7_trust_verified():
    r = trust_score(_full_facility())
    assert r["band"] == "verified"
    assert r["score"] >= 70
    assert r["unverified_fields"] == []


def test_8_trust_partial_with_gaps():
    f = _full_facility(capability=None, procedure=None, equipment=None,
                       number_doctors=None, capacity=None, year_established=None)
    r = trust_score(f)
    assert r["band"] == "partial"
    for field in ("capacity", "number_doctors", "equipment"):
        assert field in r["unverified_fields"]


def test_9_geo_mismatch_cannot_be_verified():
    r = trust_score(_full_facility(geo_status="mismatch"))
    assert r["band"] != "verified"
    assert any("conflict" in reason for reason in r["reasons"])


def test_10_no_source_is_unverified():
    r = trust_score(_full_facility(source_urls=None))
    assert r["band"] == "unverified"


# --- trust_score v2: graded credit, location, corroboration ---------------

def test_11_more_sources_scores_higher():
    one = trust_score(_full_facility(source_urls="https://a.gov.in"))
    three = trust_score(_full_facility(
        source_urls="https://a.gov.in;https://b.org;https://c.com"))
    assert three["score"] > one["score"]


def test_12_location_confidence_affects_score():
    strong = trust_score(_full_facility(geo_status="consistent", coord_source="facility"))
    weak = trust_score(_full_facility(geo_status="unknown", coord_source="pincode_fallback"))
    assert strong["score"] > weak["score"]


def test_13_specialty_corroboration_adds_points():
    backed = trust_score(_full_facility(capability="cardiac care", procedure="angioplasty"))
    unbacked = trust_score(_full_facility(capability="general help", procedure="basic visit",
                                          specialties="cardiology"))
    assert backed["score"] > unbacked["score"]   # same field lengths; only corroboration differs


def test_14_doctor_count_magnitude_is_not_a_signal():
    few = trust_score(_full_facility(number_doctors="5"))
    many = trust_score(_full_facility(number_doctors="500"))
    assert few["score"] == many["score"]   # presence only - size is never trust


def test_15_components_sum_to_score():
    r = trust_score(_full_facility())      # no PMJAY bonus in the base fixture
    assert round(sum(c["got"] for c in r["components"])) == r["score"]
    assert sum(c["max"] for c in r["components"]) == 100


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} green")
    raise SystemExit(1 if failed else 0)
