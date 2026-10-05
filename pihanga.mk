# pihanga-remote – common tasks.  Usage: make <target>   (Makefile is a symlink to this file)
.PHONY: help demo-bg e2e-bg package publish install install-browsers bundle schema proxies test e2e demo all runtime-browser shadcn-browser cdn demo-cdn e2e-cdn

SHADCN ?= ../pihanga-shadcn

# Python runs inside the Poetry-managed virtualenv (backend/.venv, see backend/poetry.toml).
POETRY ?= poetry
PY := $(POETRY) run python
VENV_OK := backend/.venv/.poetry-installed

help:
	@echo "make install  – create backend/.venv with Poetry and install the python package"
	@echo "make demo-bg  – examples/background.py: workers, broadcast, REST, threads (port 8030)"
	@echo "make e2e-bg   – browser checks against demo-bg (start it with SENSOR_INTERVAL_S=1)"
	@echo "make package  – poetry build: wheel + sdist of pihanga-remote in backend/dist"
	@echo "make publish  – bundle+schema+proxies, test, package, then poetry publish (PUBLISH_REPO=testpypi for a dry run)"
	@echo "make install-browsers – download Chromium for the Playwright e2e tests"
	@echo "make bundle   – build the generic JS bundle and copy it into the python package"
	@echo "make schema   – extract the card catalogue (JSON Schema) from @pihanga2/shadcn"
	@echo "make proxies  – generate python card proxies from the catalogue"
	@echo "make test     – runtime (vitest) + backend (pytest) unit tests"
	@echo "make demo     – run the transport demo on http://localhost:8000"
	@echo "make e2e      – browser smoke test against a running demo"
	@echo ""
	@echo "Script-tag / import-map deployment (SHADCN=path to a pihanga-shadcn checkout):"
	@echo "make runtime-browser  – shared runtime ES modules (React, ReactDOM, core)"
	@echo "make shadcn-browser   – copy browser/pihanga-shadcn/* into SHADCN and build it"
	@echo "make cdn              – assemble backend/pihanga_remote/static_cdn"
	@echo "make demo-cdn         – run examples/script_tags.py on http://localhost:8010"
	@echo "make e2e-cdn          – browser checks against demo-cdn"

# (Re)install whenever pyproject.toml or poetry.lock change.
$(VENV_OK): backend/pyproject.toml $(wildcard backend/poetry.lock)
	cd backend && $(POETRY) install
	touch $@

install: $(VENV_OK)

install-browsers: $(VENV_OK)
	cd backend && $(PY) -m playwright install chromium

runtime/node_modules:
	cd runtime && npm install --legacy-peer-deps

bundle: runtime/node_modules
	cd runtime && npx vite build
	rm -rf backend/pihanga_remote/static && cp -r runtime/dist backend/pihanga_remote/static

schema: runtime/node_modules
	cd runtime && node tools/extract-card-schemas.mjs @pihanga2/shadcn ../schemas/shadcn.cards.json

proxies: $(VENV_OK)
	cd backend && $(PY) -m pihanga_remote.codegen ../schemas/shadcn.cards.json --hints ../schemas/shadcn.hints.json -o pihanga_remote/cards/shadcn.py

test: runtime/node_modules $(VENV_OK)
	cd runtime && npx tsc --noEmit && npx vitest run
	cd backend && $(PY) -m pytest -q tests

demo: $(VENV_OK)
	cd backend && $(PY) -m uvicorn examples.transport:app --reload --port 8000

e2e: $(VENV_OK)
	cd backend && $(PY) tests/e2e/smoke.py http://localhost:8000 ../.e2e-shots

all: schema proxies bundle test

runtime-browser: runtime/node_modules
	cd runtime && npx vite build -c vite.runtime.config.ts

shadcn-browser:
	cp browser/pihanga-shadcn/vite.browser.config.ts $(SHADCN)/
	mkdir -p $(SHADCN)/src/browser && cp browser/pihanga-shadcn/src/browser/* $(SHADCN)/src/browser/
	cd $(SHADCN) && npx vite build --config vite.browser.config.ts

cdn: runtime-browser shadcn-browser
	node browser/assemble.mjs $(SHADCN)

demo-cdn: $(VENV_OK)
	cd backend && $(PY) -m uvicorn examples.script_tags:app --port 8010

e2e-cdn: $(VENV_OK)
	cd backend && $(PY) tests/e2e/smoke.py http://localhost:8010 ../.e2e-shots && $(PY) tests/e2e/script_tags.py http://localhost:8010

package: $(VENV_OK)
	cd backend && rm -rf dist && $(POETRY) build

# Rebuild everything, run the tests, build the wheel/sdist, then publish.
# PUBLISH_REPO selects the Poetry repository (e.g. `make publish PUBLISH_REPO=testpypi`
# after `poetry config repositories.testpypi https://test.pypi.org/legacy/`);
# leave unset to publish to PyPI itself.
publish: bundle schema proxies test package
ifdef PUBLISH_REPO
	cd backend && $(POETRY) publish -r $(PUBLISH_REPO)
else
	cd backend && $(POETRY) publish
endif

demo-bg: $(VENV_OK)
	cd backend && $(PY) -m uvicorn examples.background:app --port 8030

e2e-bg: $(VENV_OK)
	cd backend && $(PY) tests/e2e/background.py http://localhost:8030
