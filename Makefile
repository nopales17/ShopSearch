PYTHON ?= python3
.PHONY: serve demo pitch pitch-setup pitch-eval report backup restore test check

serve:
	$(PYTHON) -m apps.web.wsgi

demo:
	$(PYTHON) -m apps.web.demo

pitch: demo

pitch-setup:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -r requirements-pitch.txt
	$(PYTHON) -m backend.adapters.clip

pitch-eval:
	$(PYTHON) -m experiments.search_v0.evaluate_pitch

report:
	$(PYTHON) -m backend.telemetry.report

backup:
	$(PYTHON) -m backend.ops.runtime_backup

restore:
	$(PYTHON) -m backend.ops.runtime_restore

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

check:
	$(PYTHON) -m compileall -q apps backend contracts tests tools experiments/search_v0
	$(PYTHON) -m ruff check apps backend contracts tests tools experiments/search_v0
	$(PYTHON) -m ruff format --check apps backend contracts tests tools experiments/search_v0
	$(PYTHON) -m mypy apps backend contracts
	$(MAKE) test
