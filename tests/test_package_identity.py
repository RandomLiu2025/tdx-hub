from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

from tdxhub import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_python_package_uses_tdxhub_namespace_only():
    assert importlib.util.find_spec("tdxhub") is not None
    old_namespace = "moo" + "tdx"
    assert importlib.util.find_spec(old_namespace) is None


def test_distribution_name_is_distinct_from_import_and_cli_names():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["name"] == "tdxhub-sdk"
    assert project["scripts"] == {"tdxhub": "tdxhub.__main__:entry"}
    assert "numpy>=1.26,<3" in project["dependencies"]


def test_distribution_and_runtime_versions_are_synced():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["version"] == __version__


def test_holiday_javascript_is_declared_as_package_data():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["tool"]["setuptools"]["package-data"]["tdxhub.utils"] == ["holiday.js"]
    assert (ROOT / "tdxhub" / "utils" / "holiday.js").is_file()
