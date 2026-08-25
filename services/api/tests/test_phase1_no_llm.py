"""Phase 1 gate: zero LLM calls.

Phase 1's whole claim is that a hand-written spec renders without a model touching it
(spec §7). "We didn't call one" is not evidence; these are.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

from aakar.render import screenshots

RENDER_PKG = Path(screenshots.__file__).parent


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
    return found


def test_llm_calls_table_is_empty(conn: sqlite3.Connection) -> None:
    """The cost ledger has nothing in it, because nothing has spent anything."""
    assert conn.execute("SELECT COUNT(*) AS n FROM llm_calls").fetchone()["n"] == 0


def test_the_render_package_cannot_reach_a_provider() -> None:
    """Structural, not behavioural: the screenshot harness has no path to a model API.

    The Phase 3 critic will add one *around* this module — it feeds the captured PNGs to
    a VLM — but the capture code itself must stay model-free, or the Phase 1 gate stops
    meaning anything the moment Phase 3 lands.
    """
    for module in RENDER_PKG.glob("*.py"):
        imports = _imported_modules(module)
        offending = {name for name in imports if "provider" in name or name.endswith("providers")}
        assert offending == set(), f"{module.name} imports {offending}"


def test_screenshot_harness_talks_to_a_browser_not_a_model() -> None:
    imports = _imported_modules(RENDER_PKG / "screenshots.py")
    assert "playwright.sync_api" in imports
    assert not any(name.startswith("aakar.providers") for name in imports)
