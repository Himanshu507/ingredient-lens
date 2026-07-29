.PHONY: up down lint format typecheck test precommit-install

up:
	docker compose up --build

down:
	docker compose down

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy .

test:
	uv run pytest

precommit-install:
	uv run pre-commit install
