# `tests/audit/` — sources missing (M12)

This directory once held a 10-file integration/stress suite
(`test_01_auth` … `test_10_aml_circuit_breakers` + `conftest.py`), but **only
the compiled `__pycache__/*.pyc` remain — the `.py` sources are gone** and are
not in version control. They cannot be recovered from the bytecode reliably.

The `.pyc` are local build artifacts (ignored by the root `.gitignore` via
`**/__pycache__/` + `*.pyc`), so they are NOT part of the repository; you may
delete the `__pycache__/` folder safely.

**Active coverage lives in `tests/test_*.py`** — the audit-remediation
regression suite (C1–C3, H1–H6, M1–M12) wired into CI
(`.github/workflows/ci.yml`). To restore the broad integration/stress coverage
this directory implied, the suites must be re-authored from scratch.
