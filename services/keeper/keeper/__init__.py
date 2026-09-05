"""RSends Auto Split keeper.

A separate worker that preflights each active source wallet and calls
`RSendsAutoSplit.executeSplit` when there is something to distribute.

It holds a key, which is why the boundaries are written down rather than
implied:

  • The key pays gas and nothing else. `executeSplit(merchant, token)` takes no
    destination and no amount, so the worst a compromised keeper key can do is
    execute the merchant's own published policy — or waste gas. `executor.py` is
    the only module that touches it, and `abi.py` names no state-changing method
    but `executeSplit`, so a method the keeper cannot name is one it cannot
    call.

  • It holds no database credentials. The work list arrives over an internal
    HTTP endpoint; the only mutable state is Redis. In particular it cannot
    write `disabled_at`, which is the merchant's pause switch and must stay
    distinguishable from an operational back-off.

  • It never imports `app.*`. Doing so would inherit the backend's production
    guards — a Postgres URL, a JWT secret, a TLS Redis URL — for a service that
    needs none of them, and would re-couple its deploy to the backend's.

Both of the first two are pinned by tests rather than left to review:
`services/backend/tests/test_no_custodial_surface.py` (authority) and
`tests/test_no_database_authority.py` (reach).
"""
