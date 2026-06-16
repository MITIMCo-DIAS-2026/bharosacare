# BharosaCare

**Find care you can trust, near any pincode.** *Bharosa* means "trust" in Hindi.

BharosaCare helps a patient, caregiver, or community health worker enter a pincode and a needed medical specialty, then ranks the nearest real healthcare facilities that plausibly offer it — and stamps each result with a **trust badge** (verified / partial / unverified) plus a **plain-language, cited explanation of why**.

The ranking and the trust score are computed deterministically in app code. The model only explains the result and cites its source — it never decides, and never asserts a fact that isn't in the grounded text.

Built for the **Databricks Apps & Agents for Good, Data + AI Summit 2026** hackathon on Databricks Free Edition.

---

## What it does

- **User:** a community health worker, NGO outreach coordinator, or a patient/caregiver searching by pincode — the entry point every Indian already knows.
- **Beneficiary:** under-served patients facing a fragmented facility landscape where listings are inconsistent and unverifiable.
- **Workflow:** enter a pincode + specialty → BharosaCare resolves the pincode to a location, ranks nearby facilities by distance, shows each with a trust badge, a cited explanation, and an honest "unverified — see source" note where the evidence is thin. Save useful results to a shortlist.

## How it works

A deterministic core, grounded and cited explanations, and honest uncertainty — over two datasets joined on the pincode.

- **Databricks App** — the mobile-first UI; takes a pincode + specialty and renders ranked, badged result cards.
- **Lakebase (Postgres)** — holds the facility and pincode data (synced from Unity Catalog) for fast reads, plus the user's saved shortlist (operational state).
- **Agent Bricks (Knowledge Assistant)** — produces the plain-language, cited explanation for each facility, grounded only in the facility description and its source pages.
- **Data / ETL** — cleans and joins the provided facility directory with the authoritative pincode directory, and derives a deterministic completeness/confidence score and a geo-consistency flag.

```
Provided facilities (UC) ─┐
                          ├─► [ETL: clean + join on postcode] ─► curated Delta tables ─► (sync) ─► Lakebase
Pincode Directory (CSV) ──┘
                                                                                                   │
  App: pincode + specialty → resolve pincode → rank by distance → trust score → cited "why" → cards
                                                                                                   │
  Save → Lakebase (saved shortlist)                                                                │
  Agent Bricks KA (corpus = descriptions + source pages) ──────────────────────────────► cited explanation
```

## Evidence & uncertainty

- Every result links its `source_url`.
- The trust score is computed deterministically from field-coverage completeness, geo cross-validation (facility state vs. its pincode's authoritative state), and whether a citable source exists — never from the model.
- Thinly-supported fields are shown as "not stated — see source," and near-threshold cases are flagged "needs a closer look."
- "Unverified" means "we couldn't corroborate," never "untrustworthy." No person-level data; no claims that a facility or individual is fraudulent.

---

## Architecture contracts

These are the interfaces both teams build to. Don't change them without telling the other pair.

### Curated tables (Unity Catalog)

`workspace.bharosacare.facilities_curated`:

`facility_id, name, state, city, latitude, longitude, coord_source, postcode, specialties, description, capability, procedure, equipment, number_doctors, capacity, year_established, source_urls, pincode_district, pincode_state, completeness_score, geo_status` (`pmjay_match` is added only by the optional stretch milestone).

`workspace.bharosacare.pincodes_curated`:

`pincode, district, state_name, rep_lat, rep_lon, n_offices`.

### Lakebase tables

`app.facilities` and `app.pincodes` are read-only mirrors synced from the curated tables. Operational state:

```sql
CREATE TABLE IF NOT EXISTS app.saved_facilities (
  id          bigserial PRIMARY KEY,
  session_id  text NOT NULL,
  facility_id text NOT NULL,
  saved_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, facility_id)
);
CREATE INDEX IF NOT EXISTS ix_saved_session ON app.saved_facilities (session_id);
```

### Module function signatures

```python
# core.py  — deterministic, golden-tested, no I/O
def haversine_km(lat1, lon1, lat2, lon2) -> float
def rank_facilities(origin_lat, origin_lon, specialty, facilities,
                    radius_km=50, limit=10) -> list[dict]   # adds 'distance_km'; specialty match required
def trust_score(facility: dict) -> dict
#   -> {"score": int(0..100), "band": "verified"|"partial"|"unverified",
#       "reasons": list[str], "unverified_fields": list[str]}

# db.py  — parameterized queries; fresh connection per call (injected token is short-lived)
def get_pincode(pincode: str) -> dict | None        # {district, state, lat, lon}
def get_facilities_in_bbox(lat, lon, radius_km) -> list[dict]
def save_facility(session_id: str, facility_id: str) -> None
def list_saved(session_id: str) -> list[dict]

# explainer.py  — Agent Bricks client
def explain(facility: dict, specialty: str) -> dict
#   -> {"text": str, "citations": list[str], "grounded": bool}
#   on endpoint error: returns a templated string from facility fields, grounded=False
```

## Naming conventions

| Object | Name |
| --- | --- |
| Catalog / schema | `workspace.bharosacare` (confirm default catalog on day 1) |
| Curated tables | `bharosacare.facilities_curated`, `bharosacare.pincodes_curated` |
| Lakebase instance / db / schema | `bharosacare-lakebase` / `bharosacare` / `app` |
| Synced tables | `app.facilities`, `app.pincodes` |
| Operational table | `app.saved_facilities` |
| Agent Bricks endpoint | `bharosacare-explainer` |
| App / repo | `bharosacare` |

## Repo layout (planned)

```
README.md
LICENSE
app/            # Databricks App: app.py, app.yaml, requirements.txt
core.py         # deterministic ranking + trust score
db.py           # Lakebase access
explainer.py    # Agent Bricks client + fallback
test_core.py    # golden tests for the core
notebooks/      # ETL + knowledge-base staging
```

## Setup & run

The app runs as a Databricks App on Free Edition, reading from Lakebase synced tables and calling the `bharosacare-explainer` Knowledge Assistant.

1. Add the provided healthcare-facility dataset to Unity Catalog.
2. Run the ETL notebook to build the curated tables and sync them into Lakebase.
3. Build the `bharosacare-explainer` Knowledge Assistant over the facility descriptions + source pages.
4. Deploy the app and grant its service principal access to Lakebase, the tables, and the explainer endpoint.

**Live demo:** _TODO — add the deployed App URL before submission._

## Data sources & credits

- **Indian healthcare facilities** — the dataset provided by the hackathon organizers. Evidence fields are treated as claims to verify, not ground truth.
- **All India Pincode Directory** — Open Government Data Platform India (data.gov.in), sourced from India Post (Department of Posts). Used under the **Government Open Data License – India (GODL-India)**. Credit: India Post / data.gov.in. No endorsement implied.

This project is a navigation aid, not medical advice.


## License

Released under the [MIT License](LICENSE).

## Demo video

_TODO — add the ≤3-minute public video link before submission._