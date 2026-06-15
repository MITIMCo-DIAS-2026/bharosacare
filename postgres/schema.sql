-- BharosaCare — Workstream B (Jamie) — Lakebase operational schema
-- Run this ONCE in the Lakebase SQL editor (NOT the Databricks/Delta SQL editor).
--
-- SCHEMA NAME: app  (team-agreed). Must match the schema Niraj's sync lands
-- facilities/pincodes into, and db.py's SCHEMA constant.
--
-- NOTE: app.facilities and app.pincodes are READ-ONLY synced mirrors created by
-- Workstream A's Unity Catalog -> Lakebase sync. Do NOT create them here.
-- This file is the single source of truth for the operational state table.

CREATE SCHEMA IF NOT EXISTS app;

-- The user's saved shortlist (operational state the app writes to).
CREATE TABLE IF NOT EXISTS app.saved_facilities (
  id          bigserial PRIMARY KEY,
  session_id  text        NOT NULL,
  facility_id text        NOT NULL,
  saved_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, facility_id)   -- saving the same facility twice is a no-op
);

CREATE INDEX IF NOT EXISTS ix_saved_session
  ON app.saved_facilities (session_id);

-- ---------------------------------------------------------------------------
-- GRANT CHECKLIST for deploy day (Milestone 6).
-- The deployed app runs as its service principal, whose Postgres role name
-- equals the app's DATABRICKS_CLIENT_ID. Adding the Lakebase DATABASE as an
-- app resource auto-creates that role with CONNECT + CREATE. You still need to
-- grant it access to the tables it READS (the synced ones) and writes:
--
--   GRANT USAGE  ON SCHEMA app                       TO "<DATABRICKS_CLIENT_ID>";
--   GRANT SELECT ON app.facilities                   TO "<DATABRICKS_CLIENT_ID>";
--   GRANT SELECT ON app.pincodes                     TO "<DATABRICKS_CLIENT_ID>";
--   GRANT SELECT, INSERT, DELETE ON app.saved_facilities          TO "<DATABRICKS_CLIENT_ID>";
--   GRANT USAGE, SELECT ON SEQUENCE app.saved_facilities_id_seq   TO "<DATABRICKS_CLIENT_ID>";
-- ---------------------------------------------------------------------------
