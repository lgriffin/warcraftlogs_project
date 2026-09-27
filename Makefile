# Thin wrapper over scripts/dev.py, which holds the commands (and runs on Windows without make).
PYTHON ?= python

.PHONY: install hooks check fix test lint types
install:
	$(PYTHON) -m pip install -e ".[dev]"
hooks:
	pre-commit install
check:
	$(PYTHON) scripts/dev.py check
fix:
	$(PYTHON) scripts/dev.py fix
test:
	$(PYTHON) scripts/dev.py test
lint:
	$(PYTHON) scripts/dev.py format lint spelling imports deadcode
types:
	$(PYTHON) scripts/dev.py types
