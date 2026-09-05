"""Source introspection for the "this construct must not exist" guards.

Several modules carry long docstrings that NAME the anti-pattern they exist to
prevent — `tron_poller` explains at length why a positional log index loses
money, `tron_matcher` explains why the dead scorer stays dead and why folding a
base58 address corrupts it. A naive `substring in inspect.getsource(...)` guard
flags those warnings as the violation, so the guard has to read code rather
than prose.

Ordinary string literals are deliberately KEPT: an RPC method name or an event
name reaches the wire as a string, and stripping strings would hide exactly the
violation these guards look for.
"""

import ast
import inspect


def code_without_prose(module) -> str:
    """`module`'s source with docstrings and `#` comments removed.

    Line structure is preserved, so a multi-token substring like
    `"enumerate(transfers"` still matches.
    """
    return source_without_prose(inspect.getsource(module))


def source_without_prose(src: str) -> str:
    """The same, for source that cannot be reached through an import.

    `test_no_custodial_surface.py` scans `services/keeper` by PATH — that
    package is a separate service, deliberately not importable from this suite
    (it must never share a process with `app.*`), so there is no module object
    to hand `code_without_prose`.
    """
    lines = src.splitlines()

    drop: set = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            for ln in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                drop.add(ln)

    return "\n".join(
        line.split("#", 1)[0]
        for i, line in enumerate(lines, start=1)
        if i not in drop
    )
