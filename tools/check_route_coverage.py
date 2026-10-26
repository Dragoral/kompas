#!/usr/bin/env python3
"""Check that every FastAPI API path is represented in the frontend coverage matrix.

This validates inventory/documentation coverage, not runtime browser integration.
Run from repository root: python tools/check_route_coverage.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "backend" / "app" / "api"
MATRIX = ROOT / "docs" / "frontend-backend-coverage.md"
HTTP_DECORATORS = {"get", "post", "put", "patch", "delete", "options", "head", "api_route"}


def routes_in(path: Path) -> list[tuple[str, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if not isinstance(node.value.func, ast.Name) or node.value.func.id != "APIRouter":
            continue
        prefix = ""
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                prefix = kw.value.value
        for target in node.targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix

    out: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            owner = dec.func.value
            if not isinstance(owner, ast.Name) or owner.id not in prefixes or dec.func.attr not in HTTP_DECORATORS:
                continue
            suffix = ""
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                suffix = dec.args[0].value
            full_path = prefixes[owner.id] + suffix
            if not full_path.startswith("/api"):
                continue
            method = dec.func.attr.upper()
            if dec.func.attr == "api_route":
                methods_arg = next((kw.value for kw in dec.keywords if kw.arg == "methods"), None)
                if isinstance(methods_arg, ast.List):
                    for elt in methods_arg.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            out.append((elt.value.upper(), full_path, node.name))
                    continue
            out.append((method, full_path, node.name))
    return out


def main() -> int:
    matrix = MATRIX.read_text(encoding="utf-8")
    route_rows = [row for file in sorted(API_DIR.glob("*.py")) for row in routes_in(file)]
    unique_methods_paths = sorted({(method, path) for method, path, _ in route_rows})
    unique_paths = sorted({path for _, path in unique_methods_paths})
    missing = [path for path in unique_paths if path not in matrix]
    print(f"API method/path combinations: {len(unique_methods_paths)}")
    print(f"Unique API paths: {len(unique_paths)}")
    print(f"Paths represented in coverage matrix: {len(unique_paths) - len(missing)}/{len(unique_paths)}")
    if missing:
        print("Missing API paths:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 1
    print("PASS: all API paths are represented in docs/frontend-backend-coverage.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
