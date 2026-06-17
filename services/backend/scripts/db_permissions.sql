-- ═══════════════════════════════════════════════════════════════
--  RSends Backend — Database Roles & Permissions
--
--  Roles:
--    rsend_app   — Application user (SELECT/INSERT/UPDATE, no DELETE)
--    rsend_audit — Audit writer (INSERT only on audit tables)
--    rsend_admin — Full privileges (DBA / migrations)
--
--  Usage:
--    psql -U postgres -d rsend -f scripts/db_permissions.sql
-- ═══════════════════════════════════════════════════════════════

-- ── Create roles (idempotent) ────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rsend_app') THEN
        CREATE ROLE rsend_app LOGIN PASSWORD 'change_me_app';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rsend_audit') THEN
        CREATE ROLE rsend_audit LOGIN PASSWORD 'change_me_audit';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rsend_admin') THEN
        CREATE ROLE rsend_admin LOGIN PASSWORD 'change_me_admin';
    END IF;
END
$$;

-- ── Grant CONNECT ────────────────────────────────────────────
GRANT CONNECT ON DATABASE rsend TO rsend_app;
GRANT CONNECT ON DATABASE rsend TO rsend_audit;
GRANT CONNECT ON DATABASE rsend TO rsend_admin;

-- ── Schema usage ─────────────────────────────────────────────
GRANT USAGE ON SCHEMA public TO rsend_app;
GRANT USAGE ON SCHEMA public TO rsend_audit;
GRANT ALL   ON SCHEMA public TO rsend_admin;

-- ═══════════════════════════════════════════════════════════════
--  rsend_admin — Full DBA access
-- ═══════════════════════════════════════════════════════════════
GRANT ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public TO rsend_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO rsend_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL PRIVILEGES ON TABLES    TO rsend_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL PRIVILEGES ON SEQUENCES TO rsend_admin;

-- ═══════════════════════════════════════════════════════════════
--  rsend_app — Application user
--    SELECT + INSERT + UPDATE on all tables
--    NO DELETE anywhere (soft deletes via is_active flag)
--    NO UPDATE/DELETE on audit_log (append-only integrity)
-- ═══════════════════════════════════════════════════════════════

-- Sequences (for autoincrement PKs)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rsend_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO rsend_app;

-- ── Standard application tables (SELECT + INSERT + UPDATE) ───
GRANT SELECT, INSERT, UPDATE ON TABLE
    accounts,
    transactions,
    ledger_entries,
    transaction_state_log,
    transaction_logs,
    compliance_snapshots,
    anomaly_alerts,
    forwarding_rules,
    sweep_logs,
    audit_logs,
    distribution_lists,
    distribution_recipients,
    sweep_batches,
    sweep_batch_items,
    spending_ledger,
    nonce_tracker,
    circuit_breaker_states
TO rsend_app;

-- ── Audit log: INSERT only for rsend_app (NO UPDATE, NO DELETE) ─
GRANT SELECT, INSERT ON TABLE audit_log TO rsend_app;
-- Explicitly revoke UPDATE/DELETE (defense in depth)
REVOKE UPDATE, DELETE ON TABLE audit_log FROM rsend_app;

-- ── Alembic version table (read-only for app) ───────────────
GRANT SELECT ON TABLE alembic_version TO rsend_app;

-- ═══════════════════════════════════════════════════════════════
--  rsend_audit — Dedicated audit writer
--    INSERT only on audit tables
--    SELECT on everything (for chain hash verification)
--    NO UPDATE or DELETE anywhere
-- ═══════════════════════════════════════════════════════════════

-- Read access on all tables (needed for chain hash computation)
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rsend_audit;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO rsend_audit;

-- INSERT on audit tables only
GRANT INSERT ON TABLE audit_log    TO rsend_audit;
GRANT INSERT ON TABLE audit_logs   TO rsend_audit;
GRANT INSERT ON TABLE transaction_state_log TO rsend_audit;

-- Sequences for audit_log autoincrement
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rsend_audit;

-- Explicitly deny mutation on everything else
REVOKE INSERT, UPDATE, DELETE ON TABLE
    accounts,
    transactions,
    ledger_entries,
    transaction_logs,
    compliance_snapshots,
    anomaly_alerts,
    forwarding_rules,
    sweep_logs,
    distribution_lists,
    distribution_recipients,
    sweep_batches,
    sweep_batch_items,
    spending_ledger,
    nonce_tracker,
    circuit_breaker_states
FROM rsend_audit;

-- ═══════════════════════════════════════════════════════════════
--  Row-Level Security on audit_log (optional — PostgreSQL 9.5+)
--
--  Prevents UPDATE/DELETE even from rsend_admin if RLS is enabled.
--  Uncomment the block below to enable.
-- ═══════════════════════════════════════════════════════════════

-- ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
--
-- -- Allow INSERT from all roles
-- CREATE POLICY audit_log_insert ON audit_log
--     FOR INSERT
--     WITH CHECK (true);
--
-- -- Allow SELECT from all roles
-- CREATE POLICY audit_log_select ON audit_log
--     FOR SELECT
--     USING (true);
--
-- -- Deny UPDATE (no policy = denied when RLS is forced)
-- -- Deny DELETE (no policy = denied when RLS is forced)

-- ═══════════════════════════════════════════════════════════════
--  Verification queries
-- ═══════════════════════════════════════════════════════════════

-- Run these to verify permissions are correct:
--
-- SELECT grantee, table_name, privilege_type
-- FROM information_schema.table_privileges
-- WHERE grantee IN ('rsend_app', 'rsend_audit', 'rsend_admin')
-- ORDER BY grantee, table_name, privilege_type;
