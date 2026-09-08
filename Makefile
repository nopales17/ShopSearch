PYTHON ?= python3
.PHONY: run test check

run:
	$(PYTHON) -m apps.web.server

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

check:
	$(PYTHON) -m compileall -q apps backend contracts tests
	$(PYTHON) -m ruff check apps backend contracts tests
	$(PYTHON) -m ruff format --check apps backend contracts tests
	$(PYTHON) -m mypy apps backend contracts
	$(MAKE) test
