.PHONY: help start check full-check python-sanity backend-python-sanity validate-template-mappings test-project-rules backend-compile frontend-build

PYTHON ?= python3
BACKEND_PYTHON := backend/.venv/bin/python

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

python-sanity:
	@sanity_dir="$$(mktemp -d "$${TMPDIR:-/tmp}/fbm-pipeline-python-sanity.XXXXXX")" || { \
		echo "ERROR: unable to create a temporary directory for the Python sanity check." >&2; \
		exit 1; \
	}; \
	sanity_probe="$$sanity_dir/probe.py"; \
	sanity_output="$$sanity_dir/output"; \
	trap 'rm -f "$$sanity_probe" "$$sanity_output"; rmdir "$$sanity_dir" 2>/dev/null || true' EXIT HUP INT TERM; \
	sanity_challenge="$${sanity_dir##*/}"; \
	printf '%s\n' \
		'import json' \
		'import sys' \
		"challenge = \"$$sanity_challenge\"" \
		'payload = {"probe": challenge, "sum": sum((2, 3, 5))}' \
		'sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))' \
		>"$$sanity_probe"; \
	sanity_expected="{\"probe\":\"$$sanity_challenge\",\"sum\":10}"; \
	$(PYTHON) "$$sanity_probe" >"$$sanity_output" 2>/dev/null; \
	sanity_status=$$?; \
	sanity_text="$$(cat "$$sanity_output")"; \
	sanity_size="$$(wc -c <"$$sanity_output" | tr -d '[:space:]')"; \
	sanity_expected_size="$$(printf %s "$$sanity_expected" | wc -c | tr -d '[:space:]')"; \
	if [ "$$sanity_status" -ne 0 ] || [ "$$sanity_text" != "$$sanity_expected" ] || [ "$$sanity_size" -ne "$$sanity_expected_size" ]; then \
		echo "ERROR: Python sanity check failed for PYTHON=$(PYTHON); set PYTHON=/usr/bin/python3 or another working Python interpreter." >&2; \
		exit 1; \
	fi

backend-python-sanity:
	@sanity_dir="$$(mktemp -d "$${TMPDIR:-/tmp}/fbm-pipeline-backend-python-sanity.XXXXXX")" || { \
		echo "ERROR: unable to create a temporary directory for the backend Python sanity check." >&2; \
		exit 1; \
	}; \
	sanity_probe="$$sanity_dir/probe.py"; \
	sanity_output="$$sanity_dir/output"; \
	trap 'rm -f "$$sanity_probe" "$$sanity_output"; rmdir "$$sanity_dir" 2>/dev/null || true' EXIT HUP INT TERM; \
	sanity_challenge="$${sanity_dir##*/}"; \
	printf '%s\n' \
		'import json' \
		'import sys' \
		"challenge = \"$$sanity_challenge\"" \
		'payload = {"probe": challenge, "sum": sum((2, 3, 5))}' \
		'sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))' \
		>"$$sanity_probe"; \
	sanity_expected="{\"probe\":\"$$sanity_challenge\",\"sum\":10}"; \
	$(BACKEND_PYTHON) "$$sanity_probe" >"$$sanity_output" 2>/dev/null; \
	sanity_status=$$?; \
	sanity_text="$$(cat "$$sanity_output")"; \
	sanity_size="$$(wc -c <"$$sanity_output" | tr -d '[:space:]')"; \
	sanity_expected_size="$$(printf %s "$$sanity_expected" | wc -c | tr -d '[:space:]')"; \
	if [ "$$sanity_status" -ne 0 ] || [ "$$sanity_text" != "$$sanity_expected" ] || [ "$$sanity_size" -ne "$$sanity_expected_size" ]; then \
		echo "ERROR: backend/.venv/bin/python is missing or invalid; create the backend venv before running project rules." >&2; \
		exit 1; \
	fi

validate-template-mappings: python-sanity
	$(PYTHON) scripts/validate_template_mappings.py

test-project-rules: python-sanity backend-python-sanity
	$(PYTHON) scripts/test_project_rules.py

backend-compile: python-sanity
	cd backend && $(PYTHON) -m compileall -q app

frontend-build:
	cd frontend && npm run build
