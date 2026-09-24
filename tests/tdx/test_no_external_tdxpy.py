"""Dependency isolation and upstream attribution of the project-owned module."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TDX = ROOT / "tdxhub" / "tdx"
EXTERNAL = {"tdxpy", "pytdx", "cython"}


def test_external_tdxpy_is_not_a_dependency():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = list(config["project"]["dependencies"])
    for group in config["project"]["optional-dependencies"].values():
        dependencies.extend(group)
    dependencies.extend(config["build-system"]["requires"])
    for dep in dependencies:
        assert re.split(r"[\s\[<>=!~;(]", dep, maxsplit=1)[0].lower() not in EXTERNAL, dep
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert not EXTERNAL & {package["name"].lower() for package in lock["package"]}


def test_sources_do_not_import_external_or_obsolete_modules():
    violations = []
    for directory in ("tdxhub", "tests", "sample", "scripts"):
        for path in (ROOT / directory).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".")[0].lower() in EXTERNAL or name.startswith(
                        ("tdxhub._vendor", "tdxhub._tdx", "tdxhub.tdxpy_compat")
                    ):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
                    if (
                        directory == "tdxhub"
                        and not path.is_relative_to(TDX)
                        and name.startswith("tdxhub.tdx.protocol")
                    ):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: parser in business layer")
    assert not violations, violations


def test_readme_preserves_upstream_attribution():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[tdxpy](https://github.com/mootdx/tdxpy) **0.2.7**（MIT）" in readme


def test_all_tdx_modules_and_entrypoints_load_without_external_tdxpy():
    script = """
import importlib
import importlib.abc
import pkgutil
import sys

class RejectExternal(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0].lower() in {"tdxpy", "pytdx", "cython"}:
            raise ModuleNotFoundError(fullname)

sys.meta_path.insert(0, RejectExternal())
import tdxhub.tdx as tdx
for module in pkgutil.walk_packages(tdx.__path__, tdx.__name__ + "."):
    importlib.import_module(module.name)
for name in (
    "tdxhub.quotes", "tdxhub.reader", "tdxhub.parse", "tdxhub.financial.financial",
    "tdxhub.tools.customize", "tdxhub.contrib.compat", "tdxhub.__main__",
):
    importlib.import_module(name)
from tdxhub.tdx.client import StandardClient
from tdxhub.tdx.extended import ExtendedClient
assert StandardClient().to_df([{"price": 1.2}]).iloc[0]["price"] == 1.2
assert ExtendedClient().to_df([{"price": 1.2}]).iloc[0]["price"] == 1.2
assert not any(name.split(".")[0].lower() in {"tdx", "tdxpy", "pytdx", "cython"} for name in sys.modules)
assert not any(name.startswith(("tdxhub._vendor", "tdxhub._tdx", "tdxhub.tdxpy_compat")) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_license_and_module_documentation_are_consolidated():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert config["project"]["license-files"] == ["LICENSE", "AUTHORS.rst"]
    assert "tdxhub.tdx" not in config["tool"]["setuptools"]["package-data"]
    assert "tdxhub.licenses" not in config["tool"]["setuptools"]["package-data"]
    assert not (ROOT / "tdxhub" / "licenses").exists()
    assert not (TDX / "README.md").exists()
    assert not (TDX / "UPSTREAM.json").exists()
    assert (ROOT / "AUTHORS.rst").is_file()
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    for notice in (
        "Copyright (c) 2017, tdxhub",
        "MIT License",
        "Permission is hereby granted",
        "The above copyright notice",
        'THE SOFTWARE IS PROVIDED "AS IS"',
    ):
        assert notice in license_text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## TDX 模块维护" in readme
    assert "UPSTREAM.json" not in readme
    assert "tdxhub/licenses/" not in readme
    assert "tdxhub/tdx/README.md" not in readme
