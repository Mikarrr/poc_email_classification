# AI Message Router PoC

A microservice that accepts a user's message, lets an AI agent running on a local Ollama LLM decide
which department should handle it, and has the agent send the email through a tool call.

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
