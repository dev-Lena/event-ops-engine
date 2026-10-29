# Development entry points. The venv must be active (see README "설치").
PY ?= python

.PHONY: install test lint format typecheck check engine

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m black --check src tests scripts
	$(PY) -m isort --check-only src tests scripts
	$(PY) -m flake8 src tests scripts

format:
	$(PY) -m black src tests scripts
	$(PY) -m isort src tests scripts

typecheck:
	$(PY) -m mypy

check: lint typecheck test

# Intel Mac only: build the wirelog shared library from source into vendor/.
engine:
	scripts/build-wirelog.sh
