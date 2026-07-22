"""Structural regressions for contextual status placement in the sidebar."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PANEL_PATH = (
    Path(__file__).resolve().parents[1]
    / "mooblender"
    / "blender"
    / "panels.py"
)


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    """Return one top-level function from the parsed panel module."""
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    """Return one method from a named top-level panel class."""
    owner = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def _named_call_lines(function: ast.FunctionDef) -> dict[str, int]:
    """Map direct helper call names to their source order inside a function."""
    return {
        node.func.id: node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


class PanelLayoutTests(unittest.TestCase):
    """Keep asynchronous feedback adjacent to the action it describes."""

    @classmethod
    def setUpClass(cls) -> None:
        """Parse the panel once for all structural layout assertions."""
        cls.tree = ast.parse(PANEL_PATH.read_text(encoding="utf-8"))

    def test_catalog_status_belongs_to_sync_controls(self) -> None:
        """Require catalog progress to be drawn by the Sync Catalog section."""
        import_options = _function(self.tree, "_draw_import_options")
        calls = _named_call_lines(import_options)
        self.assertIn("_draw_catalog_sync_status", calls)
        string_values = {
            node.value
            for node in ast.walk(import_options)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("promob.catalog_cancel", string_values)
        self.assertIn("promob.cache_clear", string_values)

    def test_object_status_is_immediately_before_browser_search(self) -> None:
        """Require object progress after sync controls and before search."""
        calls = _named_call_lines(
            _method(self.tree, "PROMOB_PT_browser", "draw")
        )
        self.assertLess(
            calls["_draw_import_options"],
            calls["_draw_object_download_status"],
        )
        self.assertLess(
            calls["_draw_object_download_status"],
            calls["_draw_search_and_navigation"],
        )

    def test_global_status_contains_only_online_access_feedback(self) -> None:
        """Keep download state out of the global panel-top message area."""
        global_status = _function(self.tree, "_draw_background_status")
        attributes = {
            node.attr
            for node in ast.walk(global_status)
            if isinstance(node, ast.Attribute)
        }
        self.assertTrue({"is_loading", "is_syncing"}.isdisjoint(attributes))


if __name__ == "__main__":
    unittest.main()
