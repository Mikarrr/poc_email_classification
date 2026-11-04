# Email Classification PoC

Classifies incoming emails (category, priority, suggested action) with an LLM. Personal data is
pseudonymized before anything is sent to the model API.

> Work in progress.

## Quick start

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
make install          # install dependencies and the pre-commit hook
cp .env.example .env  # then fill in the values
make lint test
```

## Development

| Command | What it does |
|---|---|
| `make lint` | ruff (lint + format check) and mypy |
| `make format` | auto-fix lint issues and format the code |
| `make test` | run the tests (without live LLM calls) |
| `make cov` | run the tests with a coverage report |
