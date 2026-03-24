MAKEFLAGS += --no-print-directory

.DEFAULT_GOAL := help

.PHONY: clean fmt help lint quality run setup test typecheck

help: ## Exibe os targets disponíveis
	@echo "suapcp - Targets disponíveis"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## "} {printf "  %-15s %s\n", $$1, $$2}'

setup: ## Cria o .venv e instala as dependências
	@./make/setup.sh

run: ## Executa a aplicação  (ex: make run ARGS="-load arquivo.csv")
	@.venv/bin/python app.py $(ARGS)

test: ## Executa todos os testes
	@./make/test.sh

fmt: ## Formata o código-fonte com ruff
	@.venv/bin/ruff format .

lint: ## Verifica o código-fonte com ruff
	@.venv/bin/ruff check .

typecheck: ## Verifica tipos com mypy
	@.venv/bin/mypy .

quality: fmt lint typecheck ## Executa todas as verificações de qualidade

clean: ## Remove artefatos de build e caches
	@rm -rf __pycache__ .mypy_cache .ruff_cache dist *.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
