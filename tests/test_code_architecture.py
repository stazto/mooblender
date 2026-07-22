"""Architecture and documentation regressions for the public add-on source."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "mooblender"


class CodeArchitectureTests(unittest.TestCase):
    """Keep node construction isolated and public Python responsibilities clear."""

    def test_geometry_node_construction_has_its_own_module(self) -> None:
        """Prevent Blender node graph construction from returning to orchestration."""
        scene_source = (PACKAGE_ROOT / "blender" / "scene_builder.py").read_text(
            encoding="utf-8"
        )
        nodes_source = (PACKAGE_ROOT / "blender" / "geometry_nodes.py").read_text(
            encoding="utf-8"
        )
        scene_tree = ast.parse(scene_source)
        node_tree = ast.parse(nodes_source)

        imported_modules = {
            node.module
            for node in ast.walk(scene_tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertIn("geometry_nodes", imported_modules)

        scene_strings = {
            node.value
            for node in ast.walk(scene_tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        node_strings = {
            node.value
            for node in ast.walk(node_tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        forbidden_prefixes = ("GeometryNode", "ShaderNode")
        self.assertFalse(
            any(value.startswith(forbidden_prefixes) for value in scene_strings)
        )
        self.assertTrue(
            any(value.startswith(forbidden_prefixes) for value in node_strings)
        )

    def test_all_addon_python_units_have_docstrings(self) -> None:
        """Require an explicit responsibility on every module and callable unit."""
        missing = []
        documented_types = (
            ast.Module,
            ast.ClassDef,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        )
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, documented_types) and ast.get_docstring(node) is None:
                    name = getattr(node, "name", "<module>")
                    missing.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}:{name}")
        self.assertEqual([], missing, "Missing docstrings:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
