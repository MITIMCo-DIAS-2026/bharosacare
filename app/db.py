"""
BharosaCare — Workstream B — db.py
Lakebase Postgres access layer. Four functions the app calls (Contract 3):

    get_pincode(pincode)                        -> dict | None
    get_facilities_in_bbox(lat, lon, radius_km) -> list[dict]
    save_facility(session_id, facility_id)      -> None
    list_saved(session_id)                      -> list[dict]

SCHEMA: "app" (team-agreed). Must match the schema Niraj syncs facilities/pincodes
Workstream A syncs the curated tables into AND the schema in schema.sql. A
synced table's Postgres schema inherits the Unity Catalog schema name, so the
curated tables in UC schema `bharosacare` arrive as bharosacare.facilities /
bharosacare.pincodes. Change SCHEMA in one place if the team renames it.

Connection model (verified against current Databricks docs, Mar/May 2026):
  - Lakebase injects PGHOST/PGPORT/PGDATABASE/PGUSER/PGSSLMODE as env vars.
  - There is NO password env var. The password is a short-lived (~1h) OAuth
    token minted per connection via the Databricks SDK.
  - We use a psycopg3 connection pool whose connection class mints a FRESH
    token for every new physical connection, so a connection never carries an
    expired credential into the middle of a demo.

Requirements (add to requirements.txt):
    psycopg[binary,pool]
    databricks-sdk>=0.81.0        # 0.81.0+ has generate_database_credential()

Local testing: run `databricks auth login`, then export PGHOST/PGDATABASE/
PGPORT/PGSSLMODE/ENDPOINT_NAME, and set PGUSER to YOUR email (locally the app
runs as you, not the service principal).
"""

from __future__ import annotations

import math
import os

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from databricks.sdk import WorkspaceClient

# Postgres schema holding the synced tables AND the operational table.
# Override with env var if the team renames it; defaults to the agreed name.
SCHEMA = os.environ.get("BHAROSA_SCHEMA", "app")

# One SDK client per process; it generates fresh DB credentials on demand.
_w = WorkspaceClient()


class _OAuthConnection(psycopg.Connection):
    """A connection that fetches a fresh Lakebase OAuth token as its password."""

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs):
        endpoint_name = os.environ["ENDPOINT_NAME"]  # projects/.../branches/.../endpoints/...
        credential = _w.postgres.generate_database_credential(endpoint=endpoint_name)
        kwargs["password"] = credential.token
        return super().connect(conninfo, **kwargs)


def _conninfo() -> str:
    return (
        f"dbname={os.environ['PGDATABASE']} "
        f"user={os.environ['PGUSER']} "
        f"host={os.environ['PGHOST']} "
        f"port={os.environ.get('PGPORT', '5432')} "
        f"sslmode={os.environ.get('PGSSLMODE', 'require')}"
    )


# Pool is created lazily so importing this module never fails outside Databricks.
_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=_conninfo(),
            connection_class=_OAuthConnection,
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=10,
            open=True,
        )
    return _pool


# --- columns returned for a facility (Contract 1 schema) --------------------
_FACILITY_COLS = (
    "facility_id, name, state, city, latitude, longitude, coord_source, "
    "postcode, specialties, description, capability, procedure, equipment, "
    "number_doctors, capacity, year_established, source_urls, "
    "pincode_district, pincode_state, completeness_score, geo_status, pmjay_match"
)


def get_pincode(pincode: str) -> dict | None:
    """Resolve a pincode to its representative point. Returns
    {'district', 'state', 'lat', 'lon'} or None if the pincode is unknown."""
    sql = f"""
        SELECT district,
               state_name AS state,
               rep_lat    AS lat,
               rep_lon    AS lon
        FROM {SCHEMA}.pincodes
        WHERE pincode = %s
        LIMIT 1
    """
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(pincode).strip(),))
            return cur.fetchone()  # dict (dict_row) or None


def get_facilities_in_bbox(lat: float, lon: float, radius_km: float) -> list[dict]:
    """Cheap bounding-box prefilter around (lat, lon). Precise distance ranking
    and specialty matching happen in core.py, NOT here."""
    dlat = radius_km / 111.0
    cos_lat = max(math.cos(math.radians(lat)), 0.01)  # guard near the poles
    dlon = radius_km / (111.0 * cos_lat)

    sql = f"""
        SELECT {_FACILITY_COLS}
        FROM {SCHEMA}.facilities
        WHERE latitude  BETWEEN %s AND %s
          AND longitude BETWEEN %s AND %s
    """
    params = (lat - dlat, lat + dlat, lon - dlon, lon + dlon)
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()  # list[dict]


def save_facility(session_id: str, facility_id: str) -> None:
    """Add a facility to a session's shortlist. Idempotent — saving the same
    facility twice does nothing (UNIQUE(session_id, facility_id))."""
    sql = f"""
        INSERT INTO {SCHEMA}.saved_facilities (session_id, facility_id)
        VALUES (%s, %s)
        ON CONFLICT (session_id, facility_id) DO NOTHING
    """
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (session_id, facility_id))
        conn.commit()


def list_saved(session_id: str) -> list[dict]:
    """Return the session's saved facilities, joined to facility detail so the
    UI can render the shortlist directly. Newest first."""
    # Qualify every facility column with f. — facility_id also exists in
    # saved_facilities, so an unqualified column list is ambiguous in this join.
    facility_cols = ", ".join(f"f.{c.strip()}" for c in _FACILITY_COLS.split(","))
    sql = f"""
        SELECT s.saved_at, {facility_cols}
        FROM {SCHEMA}.saved_facilities s
        JOIN {SCHEMA}.facilities f ON f.facility_id = s.facility_id
        WHERE s.session_id = %s
        ORDER BY s.saved_at DESC
    """
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (session_id,))
            return cur.fetchall()
