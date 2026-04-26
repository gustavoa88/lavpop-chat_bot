PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
BASE_URL ?= http://127.0.0.1:8000
MIGRATIONS_DIR ?= db/migrations

.PHONY: venv install install-dev test test-integration lint compile migrate smoke run

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install -r requirements.txt

install-dev: venv
	$(PIP) install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest -q

test-integration:
	$(PYTHON) -m pytest -m integration -q

lint:
	$(PYTHON) -m ruff check app tests scripts

compile:
	$(PYTHON) -m compileall app tests scripts

migrate:
	$(PYTHON) -m scripts.db_migrate --migrations-dir $(MIGRATIONS_DIR)

smoke:
	$(PYTHON) -m scripts.production_smoke_test --base-url $(BASE_URL) --path /

run:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
