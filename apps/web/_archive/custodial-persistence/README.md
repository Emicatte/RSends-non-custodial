# Custodial persistence cluster (archived 2026-07-18)

The dormant custodial-era tx/contacts persistence layer, previously mounted invisibly in
the `/app` layout. Archived, not deleted, for its clientId→serverId mapping,
pending-confirm queue and cross-session merge logic — useful if non-custodial
payment-tracking or server-side address-book sync ever become real features.

Why it was dead (verified 2026-07-18 before removal):
- `TransactionPersistence` + `useUserTransactions` + `tx-events`: the create/update path
  hung off `rsends:tx-submitted` / `rsends:tx-confirmed` window events that nothing has
  emitted since the custodial send/swap surface was removed (Phase A); the mount-time GET
  `/api/v1/user/transactions` fetched data no component rendered.
- `ContactsPersistence` + `useUserContacts`: same shape; `rsends:contact-recorded` had no
  dispatcher.
- `PostLoginMerge`: tx half read a localStorage stash (`rsends.pendingMerge`) only ever
  written by the dead event path above; contacts half was a write-only sync of
  `rp_address_book` into a backend table nothing reads back.

Net effect of mounting them: 2 dead GETs per /app page load (+ up to 2 POSTs per login)
and red console noise wherever the backend didn't serve the routes. Zero rendered pixels
depended on any of it; all errors were swallowed.

The backend routers (`user_tx_routes` / `user_contacts_routes` / `user_routes`) are still
registered and now truly caller-less — their removal belongs to the batched backend
subtractive pass tracked in CLAUDE.md. The logout PII cleanup in `lib/logoutClient.ts`
still clears `rsends.pendingMerge` as a harmless stale-data backstop.

NOTE: intra-cluster imports were left at their original `@/…` paths; `_archive` is
excluded from tsconfig, so nothing here compiles.
