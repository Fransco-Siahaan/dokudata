# DokuData tasks. On Windows run them from Git Bash, or call the commands directly.
PY ?= $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python,$(if $(wildcard .venv/bin/python),.venv/bin/python,python))

.PHONY: install data ocr train evaluate llm-eval samples test lint api web up

install:            ## Python + web dependencies
	$(PY) -m pip install -e ".[api,ml,dev]"
	cd apps/web && npm install

data:               ## Generate the synthetic dataset (deterministic) and verify the frozen test digests
	$(PY) -m ml.synthetic.generate --out data/synthetic/v1
	$(PY) -c "from ml.common import check_frozen; check_frozen(); print('test splits match ml/data/frozen.json')"

ocr:                ## Cache OCR for every split (resumable)
	bash scripts/ocr_all.sh

train:              ## Classifiers, confidence model and decision thresholds (validation split only)
	$(PY) -m ml.training.train_classifier
	$(PY) -m ml.training.train_confidence

evaluate:           ## Full evaluation on the frozen test splits -> reports/latest, docs/evaluation-report.md
	$(PY) -m ml.evaluation.run_eval

llm-eval:           ## Methods B and C with the Claude API (prints a cost estimate; add YES=1 to run)
	$(PY) -m ml.evaluation.llm_runs $(if $(YES),--yes,)

samples:            ## Demo samples for the API
	$(PY) -m ml.synthetic.make_samples

test:
	$(PY) -m pytest -q --cov

lint:
	$(PY) -m ruff check . && $(PY) -m ruff format --check ml pipeline apps/api tests && $(PY) -m mypy
	cd apps/web && npm run lint && npm run typecheck

api:                ## API with the inline worker on http://localhost:8000
	$(PY) -m uvicorn api.main:app --app-dir apps --reload --port 8000

web:                ## Vite dev server on http://localhost:5173 (proxies /api)
	cd apps/web && npm run dev

up:                 ## Everything in Docker on http://localhost:8080
	docker compose up --build
