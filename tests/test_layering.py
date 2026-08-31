"""
Rule 8 (Development Planning Document, Section 1): engine/ and output/ must
never import from app/ or orchestration/. Checked automatically, not just
by code-review discipline.
"""
from __future__ import annotations

import ast
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_PREFIXES = ("app", "orchestration")


def _imports_in_file(path: str) -> list[str]:
    with open(path) as f:
        tree = ast.parse(f.read(), filename=path)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_engine_and_output_never_import_app_or_orchestration():
    violations = []
    for layer in ("engine", "output"):
        layer_dir = os.path.join(REPO_ROOT, layer)
        for root, _, files in os.walk(layer_dir):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(root, fname)
                for imported in _imports_in_file(path):
                    if imported.split(".")[0] in FORBIDDEN_PREFIXES:
                        violations.append(f"{path} imports '{imported}'")
    assert violations == [], violations
