"""The keeper cannot write `disabled_at`, because it cannot reach a database.

`disabled_at` is the merchant's pause switch, surfaced in their dashboard. An
operational back-off must stay distinguishable from a user action — so the
keeper's back-off lives in Redis under its own key, and the keeper holds no
database credentials at all.

That is a structural property, not a habit, and this pins it structurally: a
behavioural test can only show that the code we wrote today does not write the
column. These assertions show it *could* not.
"""

import ast
import re
from pathlib import Path

KEEPER_PKG = Path(__file__).resolve().parents[1] / "keeper"


def _code_without_prose(source: str) -> str:
    """Strip docstrings and comments, keep string literals.

    Mirrors `services/backend/tests/_source_helpers.code_without_prose`. Without
    it these guards would fire on the comments that EXPLAIN them — a module
    documenting why it must never write the merchant's pause switch would be
    indistinguishable from one that writes it. String literals stay, because a
    column named in a query is a string literal, not prose.
    """
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)

    class _Strip(ast.NodeTransformer):
        def visit_Expr(self, node):
            if (
                isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and node.value.value in docstrings
            ):
                return None
            return node

    stripped = ast.unparse(_Strip().visit(tree))
    return re.sub(r"#.*", "", stripped)

# Async and sync drivers, the ORM, and the migration tool. Anything here would
# mean the keeper had acquired a way to reach merchant state.
DB_TOKENS = (
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "psycopg2",
    "alembic",
    "DATABASE_URL",
    "database_url",
)


def _py_files():
    return sorted(p for p in KEEPER_PKG.rglob("*.py") if "__pycache__" not in p.parts)


def test_there_is_keeper_source_to_check():
    """A guard that silently scans nothing passes forever."""
    assert _py_files(), f"no keeper modules found under {KEEPER_PKG}"


def test_the_keeper_never_names_the_merchants_pause_switch():
    """Prose may name the column — several modules explain at length why they
    must not write it. CODE may not."""
    offenders = [
        f"{p.relative_to(KEEPER_PKG)}"
        for p in _py_files()
        if "disabled_at" in _code_without_prose(p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "the keeper referenced `disabled_at` in code; the merchant's pause "
        f"switch is not keeper state — use the Redis back-off key: {offenders}"
    )


def test_the_keeper_has_no_database_access():
    offenders = []
    for path in _py_files():
        code = _code_without_prose(path.read_text(encoding="utf-8"))
        for token in DB_TOKENS:
            if token in code:
                offenders.append(f"{path.relative_to(KEEPER_PKG)} names {token!r}")
    assert offenders == [], "\n".join(offenders)


def test_the_prose_stripper_does_not_hide_a_real_offender():
    """A guard built on a filter is only as good as the filter. If
    `_code_without_prose` ever swallowed real code, every test above would pass
    vacuously and say nothing."""
    # The docstring must come FIRST to be a docstring at all — a triple-quoted
    # string anywhere else is a bare expression, and the stripper is right to
    # leave it (it keeps string literals; a column named in a query is one).
    source = '"""disabled_at"""\nx = 1  # disabled_at\ny = {"disabled_at": 2}\n'

    code = _code_without_prose(source)

    assert "disabled_at" in code, "a dict key is code, not prose"
    assert code.count("disabled_at") == 1, "the comment and docstring should be gone"


def test_the_keeper_never_imports_the_backend_app_package():
    """Standalone by decision: importing `app.*` would drag in `app.config`,
    whose production guards would then demand a DATABASE_URL, an
    AUTH_JWT_SECRET and a rediss:// URL from a service that needs none of them —
    and would re-couple the keeper's deploy to the backend's."""
    offenders = []
    for path in _py_files():
        code = _code_without_prose(path.read_text(encoding="utf-8"))
        if "from app." in code or "import app." in code or "import app\n" in code:
            offenders.append(str(path.relative_to(KEEPER_PKG)))
    assert offenders == [], f"keeper modules importing the backend: {offenders}"
