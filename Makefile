PYTHON ?= python

.PHONY: dev test migrate lint typecheck install

install:
	$(PYTHON) -m pip install -e ".[dev]"

dev:
	$(PYTHON) -m uvicorn app.main:app --reload

test:
	$(PYTHON) -m pytest

migrate:
	$(PYTHON) -m alembic upgrade head

lint:
	$(PYTHON) -m ruff check app tests

typecheck:
	$(PYTHON) -m mypy app
