# Development entry points. The venv must be active (see README "설치").
PY ?= python

.PHONY: install test lint format typecheck check engine package-check wheel-smoke bench

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
	python -m zipfile -l dist/*.whl | grep -q 'event_ops_engine/samples/policy/events/synthetic-example.yaml' && echo 'wheel ships the synthetic samples'
	@python -m zipfile -l dist/*.whl | awk '{print $$1}' | sed -n 's|^event_ops_engine/samples/||p' | sort > dist/samples-in-wheel.txt
	@git ls-files data/synthetic/scenarios 'policy/events/synthetic-*.yaml' | sort > dist/samples-tracked.txt
	@diff dist/samples-tracked.txt dist/samples-in-wheel.txt || { echo 'wheel samples differ from the tracked synthetic files (diff above)'; exit 1; }
	@if python -m zipfile -l dist/*.whl | grep -q 'private'; then echo 'wheel contains a private path'; exit 1; fi

# Install the built wheel into a fresh venv and run it from a temp dir outside the repo,
# so a file missing from the wheel or a repo-relative path fails here (#80). The last two
# runs start from an empty folder and use the samples inside the wheel (#110).
SMOKE ?= $(or $(TMPDIR),/tmp)/event-ops-wheel-smoke
wheel-smoke: package-check
	rm -rf "$(SMOKE)" && $(PY) -m venv "$(SMOKE)/venv"
	"$(SMOKE)/venv/bin/pip" install -q dist/*.whl
	mkdir -p "$(SMOKE)/run/data" && cp -R data/synthetic "$(SMOKE)/run/data/" && cp -R policy "$(SMOKE)/run/"
	cd "$(SMOKE)/run" && "$(SMOKE)/venv/bin/python" -I -c "import event_ops_engine as m, sys; sys.exit(0 if m.__file__.startswith(sys.prefix + '/') else 'imported ' + m.__file__)"
	cd "$(SMOKE)/run" && "$(SMOKE)/venv/bin/event-ops" report data/synthetic/scenarios/pair-mixed.yaml | grep -q '잠정 마감 권고'
	cd "$(SMOKE)/run" && "$(SMOKE)/venv/bin/event-ops" triage data/synthetic/scenarios/triage/account-length.yaml > /dev/null
	mkdir -p "$(SMOKE)/empty" && cd "$(SMOKE)/empty" && "$(SMOKE)/venv/bin/event-ops" report "$$("$(SMOKE)/venv/bin/event-ops" samples)/pair-mixed.yaml" | grep -q '잠정 마감 권고'
	cd "$(SMOKE)/empty" && "$(SMOKE)/venv/bin/event-ops" triage "$$("$(SMOKE)/venv/bin/event-ops" samples)/triage/account-length.yaml" > /dev/null
	@echo 'installed wheel runs outside the repo, with its own samples'

# Time report and triage on seeded synthetic sign-ups (#34); about 8 s on an Intel Mac (docs/design.md 11), not run in CI.
bench:
	$(PY) scripts/bench.py

# Intel Mac only: build the wirelog shared library from source into vendor/.
engine:
	scripts/build-wirelog.sh
