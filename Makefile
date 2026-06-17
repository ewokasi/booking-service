.PHONY: help dev test lint format typecheck migrate revision up down logs shell-api shell-worker clean

help:
	@echo "make dev        - run API locally (requires postgres+redis)"
	@echo "make test       - run pytest (no docker needed)"
	@echo "make lint       - ruff check"
	@echo "make format     - ruff format + ruff check --fix"
	@echo "make typecheck  - mypy"
	@echo "make migrate    - alembic upgrade head"
	@echo "make revision m='msg' - new alembic revision (autogenerate)"
	@echo "make up         - docker-compose up --build"
	@echo "make down       - docker-compose down -v"
	@echo "make logs       - tail compose logs"

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	celery -A app.worker.celery_app.celery_app worker --loglevel=info

test:
	pytest -v

lint:
	ruff check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy app

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

up:
	docker-compose up --build

down:
	docker-compose down -v

logs:
	docker-compose logs -f api worker

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache
