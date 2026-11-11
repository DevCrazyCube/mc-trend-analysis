.PHONY: install test lint demo once status build docker-build docker-run clean

# --- Development ---

install:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -v --tb=short

test-unit:
	python -m pytest tests/unit/ -v --tb=short

test-integration:
	python -m pytest tests/integration/ -v --tb=short

lint:
	python -m ruff check src/ tests/ || true
	python -m mypy src/mctrend/ --ignore-missing-imports || true

# --- Running locally ---

demo:
	python -m mctrend.runner --demo --once

once:
	python -m mctrend.runner --once

continuous:
	python -m mctrend.runner

status:
	python -m mctrend.runner --status

# --- Docker ---

build:
	docker build -t mc-trend-analysis:latest .

docker-build: build

docker-run:
	docker-compose up

docker-demo:
	docker run --rm \
		-e ENVIRONMENT=demo \
		-e DATABASE_PATH=/tmp/demo.db \
		-e LOG_FORMAT=console \
		mc-trend-analysis:latest --demo --once

docker-status:
	docker-compose run --rm mctrend --status

docker-stop:
	docker-compose down

# --- Data management ---

clean-db:
	@echo "WARNING: This will delete the local development database."
	@read -p "Continue? [y/N] " confirm && [ "$${confirm}" = "y" ] || exit 1
	rm -f data/mctrend_dev.db data/mctrend_dev.db-wal data/mctrend_dev.db-shm

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/ htmlcov/ .coverage
