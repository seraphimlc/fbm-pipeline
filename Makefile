.PHONY: help start check full-check validate-template-mappings test-project-rules backend-compile frontend-build

PYTHON ?= python3

help:
	@echo "FBM Pipeline commands"
	@echo "  make start                       启动后端和前端"
	@echo "  make check                       运行轻量项目检查"
	@echo "  make full-check                  运行轻量检查 + 前端构建"
	@echo "  make validate-template-mappings  校验 Amazon 模板映射"
	@echo "  make test-project-rules          检查项目规则回归样例"
	@echo "  make backend-compile             编译检查后端 Python"
	@echo "  make frontend-build              构建前端"

start:
	./scripts/start.sh

check: validate-template-mappings test-project-rules backend-compile

full-check: check frontend-build

validate-template-mappings:
	$(PYTHON) scripts/validate_template_mappings.py

test-project-rules:
	$(PYTHON) scripts/test_project_rules.py

backend-compile:
	cd backend && $(PYTHON) -m compileall -q app

frontend-build:
	cd frontend && npm run build
