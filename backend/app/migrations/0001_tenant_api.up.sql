-- Multi-tenant read layer. ADDITIVE: base tables, the backend and ingestion are not changed.
-- Customers' Grafana datasources log in as one Postgres role per tenant. Such a role can read ONLY these views,
-- and each view keeps the rows of devices owned by the logged-in role. A viewer in Grafana can send any SQL
-- (POST /api/ds/query), so this is the real isolation boundary, not dashboard variables.
-- Safe to run many times (backend start). Undo: 0001_tenant_api.down.sql
CREATE SCHEMA IF NOT EXISTS tenant_api;
REVOKE ALL ON SCHEMA tenant_api FROM PUBLIC;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenant_reader') THEN
    CREATE ROLE tenant_reader NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA tenant_api TO tenant_reader;

-- Views run with the owner's rights, but current_user stays the role that is querying.
CREATE OR REPLACE VIEW tenant_api.my_devices WITH (security_barrier = true) AS
  SELECT td.compactor_id
  FROM public.tenant_devices td
  JOIN public.tenants t ON t.id = td.tenant_id
  WHERE t.db_role = current_user AND t.status = 'active';

CREATE OR REPLACE VIEW tenant_api.compactors WITH (security_barrier = true) AS
  SELECT * FROM public.compactors WHERE id IN (SELECT compactor_id FROM tenant_api.my_devices);
CREATE OR REPLACE VIEW tenant_api.compactor_status WITH (security_barrier = true) AS
  SELECT * FROM public.compactor_status WHERE compactor_id IN (SELECT compactor_id FROM tenant_api.my_devices);
CREATE OR REPLACE VIEW tenant_api.readings WITH (security_barrier = true) AS
  SELECT * FROM public.readings WHERE compactor_id IN (SELECT compactor_id FROM tenant_api.my_devices);
CREATE OR REPLACE VIEW tenant_api.alerts WITH (security_barrier = true) AS
  SELECT * FROM public.alerts WHERE compactor_id IN (SELECT compactor_id FROM tenant_api.my_devices);
CREATE OR REPLACE VIEW tenant_api.pickups WITH (security_barrier = true) AS
  SELECT * FROM public.pickups WHERE compactor_id IN (SELECT compactor_id FROM tenant_api.my_devices);
CREATE OR REPLACE VIEW tenant_api.materials AS SELECT * FROM public.materials;   -- price list, not customer data

GRANT SELECT ON ALL TABLES IN SCHEMA tenant_api TO tenant_reader;

-- Tenant roles must not be able to create anything: no temp tables, no objects in public.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
DO $$ BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
END $$;
