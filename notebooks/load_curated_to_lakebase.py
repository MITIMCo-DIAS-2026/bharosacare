# BharosaCare — one-time copy of curated UC tables into Lakebase Postgres
# ----------------------------------------------------------------------------
# Run this in a Databricks NOTEBOOK (serverless is fine). It reads the curated
# Delta tables and writes them straight into Lakebase Postgres with a normal
# Postgres driver — NO Lakeflow pipeline, so it sidesteps the pipeline limit
# that blocked the synced table. Paste each section into its own notebook cell.
#
# Owners: this is really an A+B job — Niraj owns the curated tables, Jamie owns
# the Lakebase connection. Run it whenever the curated tables are refreshed.


# ===== CELL 1 — install deps (notebook magic; must be its own cell) =========
# %pip install --quiet "psycopg[binary]" "sqlalchemy>=2.0" "databricks-sdk>=0.81.0"
# dbutils.library.restartPython()


# ===== CELL 2 — fill these in ===============================================
CURATED_CATALOG = "workspace"        # your default catalog (check in Catalog Explorer)
CURATED_SCHEMA  = "bharosacare"
PGHOST          = "PASTE_FROM_CONNECT_MODAL"   # Lakebase > Connect > "Parameters only" > PGHOST
PGUSER          = "dais2026hackathon@mitimco.mit.edu"        # YOUR Databricks email (the notebook runs as you)
ENDPOINT_NAME   = "projects/dais-postgres-db/branches/production/endpoints/primary"
TARGET_SCHEMA   = "app"


# ===== CELL 3 — read the curated tables (tiny -> pandas) ====================
fac = spark.table(f"{CURATED_CATALOG}.{CURATED_SCHEMA}.facilities_curated").toPandas()
pin = spark.table(f"{CURATED_CATALOG}.{CURATED_SCHEMA}.pincodes_curated").toPandas()
print(f"facilities: {len(fac)} rows -> {list(fac.columns)}")
print(f"pincodes  : {len(pin)} rows -> {list(pin.columns)}")
# SANITY CHECK before loading:
#   - column names must be the CURATED names (city, number_doctors, ...), not raw
#     (address_city, numberDoctors, ...). If they're still raw, fix it in Niraj's
#     curation step, not here — db.py expects the curated names.
#   - latitude / longitude must be numeric (float64 here), not strings.
print(fac.dtypes[["latitude", "longitude"]])


# ===== CELL 4 — connect to Lakebase with a fresh OAuth token ================
from databricks.sdk import WorkspaceClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

token = WorkspaceClient().postgres.generate_database_credential(endpoint=ENDPOINT_NAME).token
url = URL.create(
    "postgresql+psycopg",
    username=PGUSER, password=token,
    host=PGHOST, port=5432, database="databricks_postgres",
    query={"sslmode": "require"},
)
engine = create_engine(url)

with engine.begin() as conn:
    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {TARGET_SCHEMA}"))
print("connected, schema ready")


# ===== CELL 5 — load (drop & recreate from the DataFrame) ===================
# if_exists="replace" auto-creates the table from the DataFrame dtypes, so
# latitude/longitude land as double precision and the rest as text.
fac.to_sql("facilities", engine, schema=TARGET_SCHEMA,
           if_exists="replace", index=False, method="multi", chunksize=1000)
pin.to_sql("pincodes", engine, schema=TARGET_SCHEMA,
           if_exists="replace", index=False, method="multi", chunksize=1000)
print("loaded")


# ===== CELL 6 — verify ======================================================
with engine.connect() as conn:
    for t in ("facilities", "pincodes"):
        n = conn.execute(text(f"SELECT count(*) FROM {TARGET_SCHEMA}.{t}")).scalar()
        print(f"{TARGET_SCHEMA}.{t}: {n} rows")
    # spot-check the bbox-critical columns came over as numbers
    r = conn.execute(text(
        f"SELECT min(latitude), max(latitude), min(longitude), max(longitude) "
        f"FROM {TARGET_SCHEMA}.facilities")).one()
    print("lat/long range:", r)


# ===== CELL 7 — IMPORTANT: re-apply the service-principal grants ============
# to_sql("replace") recreated the tables, which DROPS any prior grants. The app's
# service principal needs SELECT again. Run these (here or in the Lakebase SQL
# editor) once the app's DATABRICKS_CLIENT_ID is known (app Environment tab):
#
#   GRANT USAGE  ON SCHEMA app          TO "<DATABRICKS_CLIENT_ID>";
#   GRANT SELECT ON app.facilities      TO "<DATABRICKS_CLIENT_ID>";
#   GRANT SELECT ON app.pincodes        TO "<DATABRICKS_CLIENT_ID>";
#
# (Re-run this every time you re-run the copy, since replace drops the grants.)
