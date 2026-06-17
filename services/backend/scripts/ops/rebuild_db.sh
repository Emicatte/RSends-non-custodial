#!/bin/sh
# rebuild_db.sh — one-shot: DROP public schema + alembic upgrade head
#
# USE WHEN:
#   Prod DB is in an orphan state (tables exist but alembic_version
#   does not, or schema has drifted from migration history). Typical
#   one-time recovery after a legacy metadata.create_all() run.
#
# DO NOT:
#   - Wire this into any deploy pipeline
#   - Run in CI
#   - Run on a DB with real user data — script aborts if counts > 0
#
# REQUIRES (env):
#   DBURL         sync URL (postgresql://...) used by psql
#   DATABASE_URL  async URL (postgresql+asyncpg://...) used by alembic
#
# INVOCATION:
#   export DBURL="postgresql://user:pass@host/db"
#   export DATABASE_URL="postgresql+asyncpg://user:pass@host/db"
#   source venv/bin/activate
#   ./scripts/ops/rebuild_db.sh
#   # prompts interactively: DROP PROD DB

set -e

die()  { printf "\n[rebuild_db] ERROR: %s\n" "$1" >&2; exit 1; }
note() { printf "[rebuild_db] %s\n" "$1"; }

# ─── 1. Pre-flight checks ───────────────────────────────────────
[ -n "$DBURL" ]        || die "DBURL is not set (sync psql URL required)"
[ -n "$DATABASE_URL" ] || die "DATABASE_URL is not set (async URL required by alembic)"

case "$DATABASE_URL" in
  *"+asyncpg"*) ;;
  *) die "DATABASE_URL must contain '+asyncpg' driver (got: $DATABASE_URL)" ;;
esac

[ -x ./venv/bin/alembic ] || \
  die "./venv/bin/alembic not found or not executable — run: source venv/bin/activate && pip install -r requirements.txt"

command -v psql >/dev/null 2>&1 || \
  die "psql not on PATH — install postgres client (brew install libpq && brew link --force libpq)"

[ -f alembic/versions/0032_github_auth.py ] || \
  die "alembic/versions/0032_github_auth.py missing — stale checkout? run: git pull"

psql "$DBURL" -v ON_ERROR_STOP=1 -c "SELECT 1;" >/dev/null || \
  die "cannot connect to DBURL"

note "pre-flight OK"

# ─── 2. Interactive confirmation ─────────────────────────────────
[ -t 0 ] || die "stdin is not a TTY — refusing to drop DB non-interactively"

MASKED=$(echo "$DBURL" | sed 's|://[^@]*@|://***@|')
printf "\n"
note "=========================================="
note "  PROD DB REBUILD — DESTRUCTIVE OPERATION"
note "=========================================="
note "Target: $MASKED"
printf "\nType exactly  DROP PROD DB  to continue: "
read -r CONFIRM
[ "$CONFIRM" = "DROP PROD DB" ] || die "confirmation mismatch — aborted"

# ─── 3. Row-count paranoia check ────────────────────────────────
count_rows() {
  psql "$DBURL" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM $1;"
}

USERS=$(count_rows users)
TXS=$(count_rows user_transactions)
ORGS=$(count_rows organizations)

note "Current row counts: users=$USERS  user_transactions=$TXS  organizations=$ORGS"
if [ "$USERS" != "0" ] || [ "$TXS" != "0" ] || [ "$ORGS" != "0" ]; then
  die "refusing to drop non-empty DB, manual intervention required"
fi

# ─── 4. DROP + CREATE + GRANT ───────────────────────────────────
note "dropping and recreating public schema..."
psql "$DBURL" -v ON_ERROR_STOP=1 <<'SQL'
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO rsends;
GRANT ALL ON SCHEMA public TO public;
SQL

# ─── 5. Post-drop verification ──────────────────────────────────
TABLES_AFTER_DROP=$(psql "$DBURL" -v ON_ERROR_STOP=1 -tAc \
  "SELECT count(*) FROM pg_tables WHERE schemaname='public';")
TYPES_AFTER_DROP=$(psql "$DBURL" -v ON_ERROR_STOP=1 -tAc \
  "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public' AND t.typtype='e';")

[ "$TABLES_AFTER_DROP" = "0" ] || die "post-drop: public schema still has $TABLES_AFTER_DROP tables"
[ "$TYPES_AFTER_DROP" = "0" ]  || die "post-drop: public schema still has $TYPES_AFTER_DROP ENUM types"
note "schema is clean (0 tables, 0 enums)"

# ─── 6. alembic upgrade head ────────────────────────────────────
note "running alembic upgrade head..."
./venv/bin/alembic upgrade head || die "alembic upgrade head failed"

# ─── 7. Post-upgrade verification ───────────────────────────────
VERSION=$(psql "$DBURL" -v ON_ERROR_STOP=1 -tAc "SELECT version_num FROM alembic_version;")
[ -n "$VERSION" ] || die "alembic_version empty after upgrade"
note "alembic_version = $VERSION"

USERS_COLS=$(psql "$DBURL" -v ON_ERROR_STOP=1 -tAc \
  "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='users';")

MISSING=""
for col in github_sub github_username password_hash password_set_at email_verified_at \
           deletion_requested_at deletion_scheduled_for deletion_reason active_org_id; do
  echo "$USERS_COLS" | grep -qx "$col" || MISSING="$MISSING $col"
done
[ -z "$MISSING" ] || die "users table missing columns:$MISSING"

TABLE_COUNT=$(psql "$DBURL" -v ON_ERROR_STOP=1 -tAc \
  "SELECT count(*) FROM pg_tables WHERE schemaname='public';")
[ "$TABLE_COUNT" -ge 40 ] || die "only $TABLE_COUNT tables after upgrade (expected >= 40)"
note "tables: $TABLE_COUNT  |  users has all 9 expected columns"

# ─── 8. Success summary ─────────────────────────────────────────
cat <<EOF

[rebuild_db] OK  schema dropped and recreated
[rebuild_db] OK  alembic upgraded to $VERSION
[rebuild_db] OK  users table has all 9 expected columns
[rebuild_db] OK  $TABLE_COUNT tables in public schema

Done. Verify in app: POST /api/v1/auth/google should no longer raise
UndefinedColumnError.
EOF
