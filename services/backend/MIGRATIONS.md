# Database Migrations — Expand/Contract Rules (RSends Backend)

## TL;DR

Migrations run as a Render **Pre-Deploy Command** (`alembic upgrade head`) — **once**,
before the new version is promoted, on a **separate** instance, while the **old** pods
keep serving the **OLD** schema. A failed pre-deploy migration **aborts the deploy**
(the old version keeps running). Therefore **every migration MUST be backward-compatible
with the currently-running (previous) code.** Schema changes and the code that *requires*
them ship in **separate** releases.

> Wiring: [scripts/entrypoint.sh](scripts/entrypoint.sh) guards boot-time migration behind
> `RUN_MIGRATIONS_ON_BOOT` (default `1` = legacy behavior). In production set the Render
> Pre-Deploy Command to `alembic upgrade head` and env `RUN_MIGRATIONS_ON_BOOT=0`. See
> [DEPLOY_CHECKLIST.md](DEPLOY_CHECKLIST.md) §3.

---

## The Expand / Contract rule

1. **EXPAND** (release N): add the new schema in a backward-compatible way — nullable
   columns, new tables, new **nullable** FKs, or columns that are `NOT NULL` **with** a
   `server_default`. Old code keeps working unchanged.
2. **MIGRATE**: pre-deploy runs `alembic upgrade head` before the new version is promoted.
3. **DEPLOY** the new code (release N) that *can* use the new schema but does **not** require
   anything the old code couldn't already satisfy.
4. **CONTRACT** (release N+1 or later): only after all old pods are gone, remove the old
   column / drop the temporary default / tighten to `NOT NULL` / drop the old index.

---

## Forbidden in a single release

Never combine any of these with the code that depends on them — they break the old pod
still serving during the rolling window:

- [ ] **DROP** a column / table that the previous code still reads or writes.
- [ ] **RENAME** a column / table (in the DB this is drop + add — both old and new break).
- [ ] **ADD a `NOT NULL` column WITHOUT a `server_default`** — old `INSERT`s that omit the
      column fail. Need `NOT NULL`? Do it in three steps across releases: add nullable →
      backfill → set `NOT NULL` later. (Adding `NOT NULL` **WITH** a `server_default` is fine.)
- [ ] **Flip an existing column to `NOT NULL`** while old code still inserts rows leaving it NULL.
- [ ] **Create a UNIQUE index NON-concurrently** on a hot/large table (write-blocking lock
      during the build).
- [ ] **Dedup `DELETE` + add UNIQUE in one migration** against live writes, unless the dedup
      is provably safe and idempotent on production data.

---

## `CREATE INDEX CONCURRENTLY` — note + current blocker

`CREATE INDEX CONCURRENTLY` **cannot run inside a transaction block.** Today
[alembic/env.py](alembic/env.py) runs **all** pending migrations inside a **single**
transaction (`transaction_per_migration` is not set → default `False`; one
`context.begin_transaction()` in `do_run_migrations`). So CONCURRENTLY is **not possible
yet**.

**Future improvement (do NOT change now):** set `transaction_per_migration=True` (or use
`op.get_context().autocommit_block()`) in `env.py` so an individual migration can issue
`CREATE INDEX CONCURRENTLY`. Until then, build new unique indexes on large/hot tables during
a low-traffic window and accept the lock, or create them outside Alembic.

There is also **no `lock_timeout` / `statement_timeout`** configured in `env.py`. A future
improvement is to bound DDL waits (e.g. `SET lock_timeout = '5s'`) so a blocked migration
fails fast instead of hanging the deploy.

---

## Known pre-existing risky migrations (ALREADY APPLIED — do NOT rewrite)

> **Stale section — read this first.** The migrations listed below belong to the *pre-squash*
> numbering. That chain was replaced by `0001_noncustodial_baseline` (which builds the schema
> from `Base.metadata`), the files were deleted at commit `9a425616`, and the links in this
> table no longer resolve. They are kept as cautionary examples only; none of them is "already
> applied" to anything you can inspect today. The live chain is `0001` → `0017`.
>
> One of them left a real hole. `0030` also created two **partial unique indexes** on
> `user_wallets` (`uq_user_wallets_active_org`, `uq_user_wallets_one_primary_org`), and the
> squash dropped them on the floor: the model carried no `__table_args__`, so `create_all` never
> reproduced them, and `pg_indexes` on production confirmed their absence. Nothing enforced "one
> active primary wallet per org" or "no duplicate active address per org" — the tenancy key for
> payments, webhooks and API keys — and the `IntegrityError` → 409 handlers written against them
> were inert. Restored by **`0017_user_wallets_uniques`**, in the model *and* in a revision,
> since `create_all` covers only new databases and a revision covers only migrated ones.

These are in production and **must not be edited**. They are listed as cautionary examples
of what the rule above exists to prevent.

| Migration | Risk (one line) |
|-----------|-----------------|
| `0030_org_scope_api_keys_wallets` *(deleted in the squash; see the note above)* | Flips `user_api_keys.org_id` and `user_wallets.org_id` from nullable to `NOT NULL` (+ index drop/recreate); old code unaware of `org_id` ⇒ NOT NULL violation during the rolling window. Its **index half was lost in the squash and never existed in production** — restored by `0017_user_wallets_uniques`. |
| [0032_github_auth](alembic/versions/0032_github_auth.py) | `CREATE UNIQUE INDEX ix_users_github_sub` **not** concurrently ⇒ write-blocking lock on `users` during the build. |
| [0036_split_exec_unique_srctx](alembic/versions/0036_split_exec_unique_srctx.py) | Dedup `DELETE` on `split_executions` then `ADD UNIQUE(contract_id, source_tx_hash)` — destructive pre-step + new unique constraint in one release. |
| [0037_add_account_type](alembic/versions/0037_add_account_type.py) | Adds `users.account_type` `NOT NULL` with a **temporary** `server_default` then **drops** the default ⇒ afterward the column is `NOT NULL` with no default; old pods inserting a user hit a NOT NULL violation. |

---

## Reference: recent migrations that were safe/additive

Use these as the template for compatible change:

- **0029_organizations** — new tables + a nullable FK on `users`.
- **0031_email_password_auth** — adds nullable columns; **relaxes** `google_sub` to nullable.
- **0033_forwarding_rules_version** — `NOT NULL` **with** a `server_default` (safe).
- **0035_split_contracts_owner_address** — nullable column + non-destructive backfill.
- **0038_add_signup_profile_fields** — nullable columns only.
