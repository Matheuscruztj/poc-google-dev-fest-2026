PYTHON ?= python

.PHONY: setup run lint typecheck test e2e build compose-check postgres-check check pre-push release-check compose-up compose-down compose-logs eval-offline eval-live eval-compare eval-rag report-metrics

setup:
	$(PYTHON) -c 'import sys; assert sys.version_info[:2] == (3, 11), "Use Python 3.11"'
	$(PYTHON) -m pip install --require-hashes -r requirements/py311-dev-agent.txt
	$(PYTHON) -m pip install --no-deps -e .

run:
	$(PYTHON) -m uvicorn app.main:app --host "$${EVENTOPS_HOST:-127.0.0.1}" --port "$${EVENTOPS_PORT:-8000}"

compose-up:
	docker compose up --build -d

compose-up-gpu:
	EVENTOPS_AGENT_MODE=local docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu up --build -d

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f app

lint:
	$(PYTHON) -m ruff check app mcp_server tests scripts
	$(PYTHON) -m ruff format --check app mcp_server tests scripts
	npm run lint

typecheck:
	$(PYTHON) -m mypy --explicit-package-bases app mcp_server scripts

test:
	$(PYTHON) -m pytest -m 'not e2e' --cov=app.schedule --cov=app.faq --cov=app.reservations --cov=app.storage --cov-branch --cov-report=term-missing --cov-report=xml
	$(PYTHON) -m coverage json -o coverage.json
	$(PYTHON) scripts/checks/check_branch_coverage.py coverage.json

e2e:
	$(PYTHON) -m pytest -m e2e --junitxml=test-results/e2e.xml

build:
	$(PYTHON) scripts/checks/check_build.py

compose-check:
	$(PYTHON) scripts/checks/check_compose.py

postgres-check:
	$(PYTHON) scripts/checks/check_postgres.py

# Laboratório local descartável; não acessa Google Cloud nem exige API key.

eval-offline:
	$(PYTHON) scripts/evals/run_evals.py --mode offline --rounds 1

eval-live:
	$(PYTHON) scripts/evals/run_evals.py --mode live --rounds 3 --max-requests 123 $(if $(LIVE_CONFIRM),--confirm-live)

eval-compare:
	$(PYTHON) scripts/evals/run_comparison.py --rounds 3

eval-rag:
	$(PYTHON) scripts/evals/eval_rag.py --mode "$${RAG_EVAL_MODE:-lexical}"

report-metrics:
	@test -n "$(REPORT)" || (echo 'Use make report-metrics REPORT=reports/run/comparison.json' && exit 2)
	$(PYTHON) scripts/evals/report_metrics.py "$(REPORT)"

check: lint typecheck test e2e eval-offline

pre-push: check build compose-check

release-check: check build compose-check
	$(PYTHON) scripts/checks/release_check.py

