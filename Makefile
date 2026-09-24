.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test check hooks clean

help:  ## Lista os comandos
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install:  ## Instala as dependências (Poetry)
	poetry install

lint:  ## Ruff (lint + checagem de formatação)
	poetry run ruff check .
	poetry run ruff format --check .

format:  ## Corrige lint e formata o código
	poetry run ruff check --fix .
	poetry run ruff format .

typecheck:  ## mypy
	poetry run mypy

test:  ## pytest com cobertura
	poetry run pytest --cov=the_bank_project

check: lint typecheck test  ## O mesmo que o CI roda

hooks:  ## Instala os hooks do pre-commit
	poetry run pre-commit install

clean:  ## Remove caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
