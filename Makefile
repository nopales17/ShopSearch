PYTHON ?= python3
.PHONY: run pitch pitch-setup pitch-eval test check

run:
	$(PYTHON) -m apps.web.server

pitch:
	$(PYTHON) -m apps.web.pitch_server

pitch-setup:
	$(PYTHON) -m pip install -r requirements-pitch.txt
	$(PYTHON) -m backend.adapters.clip

pitch-eval:
	$(PYTHON) -m experiments.search_v0.evaluate_pitch

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

check:
	$(PYTHON) -m compileall -q apps backend contracts tests tools experiments/search_v0
	$(PYTHON) -m ruff check apps backend contracts tests tools experiments/search_v0
	$(PYTHON) -m ruff format --check apps backend contracts tests tools experiments/search_v0
	$(PYTHON) -m mypy apps backend contracts
	$(MAKE) test
