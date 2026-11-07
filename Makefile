# Development entry points. The venv must be active (see README "설치").
PY ?= python

.PHONY: install test lint format typecheck check engine bench

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

package-check:
	rm -rf build dist && python -m pip wheel . --no-deps -q -w dist && python -m zipfile -l dist/*.whl | grep -q 'event_ops_engine/rules/triage.dl' && echo 'wheel ships rules/*.dl'

# Time report and triage on seeded synthetic sign-ups (#34); a few minutes, not run in CI.
bench:
	$(PY) scripts/bench.py

# Intel Mac only: build the wirelog shared library from source into vendor/.
engine:
	scripts/build-wirelog.sh
