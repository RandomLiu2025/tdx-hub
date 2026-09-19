from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_make(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_help_lists_supported_workflows():
    output = run_make("help").stdout

    for target in (
        "sync",
        "test",
        "test-network",
        "test-vipdoc",
        "lint",
        "format",
        "format-check",
        "lock-check",
        "deps-check",
        "build",
        "pack",
        "package-check",
        "check",
        "clean",
    ):
        assert target in output


def test_build_uses_uv_without_implicit_cleanup():
    output = run_make("--dry-run", "build").stdout

    assert "uv build" in output
    assert "rm -rf" not in output
    assert "pip wheel" not in output


def test_specialized_tests_override_default_marker_filter():
    network_output = run_make("--dry-run", "test-network").stdout
    vipdoc_output = run_make(
        "--dry-run",
        "test-vipdoc",
        "TDXHUB_TDXDIR=/tmp/tdx",
    ).stdout

    assert "-m network" in network_output
    assert "-m integration" in vipdoc_output
    assert 'TDXHUB_TDXDIR="/tmp/tdx"' in vipdoc_output


def test_pack_builds_source_tar_gz_without_implicit_cleanup():
    output = run_make("--dry-run", "pack").stdout

    assert "tar -czf" in output
    assert "src.tar.gz" in output
    assert "rm -rf build/pack" in output
    assert "rm -rf dist" not in output
    assert "cp -R tdxhub tests docs sample scripts .github" in output
    for name in (
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "AUTHORS.rst",
        "requirements.txt",
        "tox.ini",
        "Makefile",
    ):
        assert name in output


def test_check_stays_deterministic_and_non_destructive():
    output = run_make("--dry-run", "check").stdout

    assert "-m network" not in output
    assert "-m integration" not in output
    assert "rm -rf" not in output
