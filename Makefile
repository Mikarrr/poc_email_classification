.PHONY: install run lint format test cov clean

install:
	uv sync
	uv run pre-commit install

run:
	PYDANTIC_AI_NO_BANNER=1 uv run uvicorn email_classifier.api.app:create_app --factory --reload

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest -m "not live"

cov:
	uv run pytest -m "not live" --cov --cov-report=term-missing

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
