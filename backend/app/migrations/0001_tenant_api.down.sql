-- Undo multi-tenancy. Readings, alerts, pickups and compactors are NOT touched.
-- DESTROYS tenant accounts and device ownership. Delete the customer Grafana orgs separately.
--   docker compose exec -T postgres psql -U compactor -d compactor < backend/app/migrations/0001_tenant_api.down.sql
DROP SCHEMA IF EXISTS tenant_api CASCADE;

DO $$
DECLARE r text;
BEGIN
  IF to_regclass('public.tenants') IS NOT NULL THEN
    FOR r IN SELECT db_role FROM public.tenants WHERE db_role IS NOT NULL LOOP
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
        EXECUTE format('DROP ROLE %I', r);
      END IF;
    END LOOP;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenant_reader') THEN
    DROP ROLE tenant_reader;
  END IF;
  EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO PUBLIC', current_database());
END $$;

DROP TABLE IF EXISTS auth_sessions;
DROP TABLE IF EXISTS tenant_devices;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS tenants;
