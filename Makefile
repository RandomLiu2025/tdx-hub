.DEFAULT_GOAL := help

UV ?= uv
UVX ?= uvx
UV_RUN := $(UV) run --all-extras --frozen
TDXHUB_TDXDIR ?=
PROJECT_VERSION := $(shell awk -F '"' '/^version = / { print $$2; exit }' pyproject.toml)
DIST_BASENAME := tdxhub_sdk-$(PROJECT_VERSION)
SDIST := dist/$(DIST_BASENAME).tar.gz
PACK_TAR := dist/$(DIST_BASENAME)-src.tar.gz
PACK_NAME := $(DIST_BASENAME)-src
PACK_STAGING := build/pack/$(PACK_NAME)
WHEEL := dist/$(DIST_BASENAME)-py3-none-any.whl

.PHONY: help sync install test test-network test-vipdoc lint lint-all format format-check \
	lock-check deps-check build pack package-check check clean

help: ## Show available development commands
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## Sync all runtime and test dependencies with uv
	$(UV) sync --all-extras

install: sync ## Alias for sync

test: ## Run the deterministic offline test suite
	$(UV_RUN) pytest

test-network: ## Run tests that require live network services
	$(UV_RUN) pytest -m network

test-vipdoc: ## Run local TDX integration tests (requires TDXHUB_TDXDIR)
	@test -n "$(TDXHUB_TDXDIR)" || { echo "TDXHUB_TDXDIR is required" >&2; exit 2; }
	TDXHUB_TDXDIR="$(TDXHUB_TDXDIR)" $(UV_RUN) pytest -m integration tests/integration

lint: ## Run critical Ruff and Python compilation checks
	$(UVX) ruff check --select E9,F63,F7,F82 tdxhub tests
	$(UV_RUN) python -m compileall -q tdxhub tests

lint-all: ## Report all Ruff rules, including the legacy-code backlog
	$(UVX) ruff check tdxhub tests

format: ## Format Python sources with Ruff
	$(UVX) ruff format tdxhub tests

format-check: ## Check Python formatting without modifying files
	$(UVX) ruff format --check tdxhub tests

lock-check: ## Verify uv.lock matches pyproject.toml
	$(UV) lock --check

deps-check: ## Check the active environment for dependency conflicts
	$(UV) pip check

build: ## Build the source distribution and wheel with uv
	$(UV) build

pack: ## Package project source code as a tar.gz snapshot
	rm -rf build/pack
	mkdir -p $(PACK_STAGING)
	cp -R docs tdxhub sample scripts .github $(PACK_STAGING)/
	cp -R .pre-commit-config.yaml .drone.yml .coveragerc mkdocs.yml LICENSE Dockerfile .gitignore pyproject.toml README.md AUTHORS.rst requirements.txt tox.ini Makefile $(PACK_STAGING)/
	find $(PACK_STAGING) -type d -name __pycache__ -prune -exec rm -rf {} +
	find $(PACK_STAGING) -type d -name '*.egg-info' -prune -exec rm -rf {} +
	find $(PACK_STAGING) -type f \( -name '*.py[co]' -o -name '.DS_Store' \) -delete
	mkdir -p dist
	tar -czf $(PACK_TAR) -C build/pack $(PACK_NAME)
	@ls -lh $(PACK_TAR)

package-check: build ## Validate metadata and required wheel resources
	$(UVX) twine check $(SDIST) $(WHEEL)
	$(UV_RUN) python -c "import zipfile; from pathlib import Path; wheel = Path('$(WHEEL)'); archive = zipfile.ZipFile(wheel); names = archive.namelist(); metadata = archive.read(next(name for name in names if name.endswith('.dist-info/METADATA'))).decode(); assert 'tdxhub/utils/holiday.js' in names; assert 'Name: tdxhub-sdk' in metadata; assert 'Version: $(PROJECT_VERSION)' in metadata"

check: lock-check deps-check lint test package-check ## Run all deterministic local quality gates

clean: ## Remove generated build, test, coverage, and Python cache files
	rm -rf build dist .pytest_cache .ruff_cache .tox htmlcov .coverage *.egg-info
	find tdxhub tests -type d -name __pycache__ -prune -exec rm -rf {} +
	find tdxhub tests -type f -name '*.py[co]' -delete
