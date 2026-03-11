# Secretary Agent Makefile

SECRETARY_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
REPO_ROOT := $(abspath $(SECRETARY_DIR)/..)
INSTRUCTIONS := $(SECRETARY_DIR)/INSTRUCTIONS.md
VALIDATOR := $(SECRETARY_DIR)/block_report_validator.py
JOURNAL_HELPER := $(REPO_ROOT)/journal_helper.py
REPORT_DIR := $(SECRETARY_DIR)/blocked_report
DATE ?= $(shell date +%F)
OUTPUT ?= codex-secretary-final.txt
OUTPATH := $(SECRETARY_DIR)/$(OUTPUT)
SOURCE_BLOCKED ?= $(SECRETARY_DIR)/input/blocked
SOURCE_TO_REVIEW ?= $(SECRETARY_DIR)/input/to_review

PROMPT := Follow secretary/INSTRUCTIONS.md exactly. For date $(DATE), read submissions from $(SOURCE_BLOCKED) and $(SOURCE_TO_REVIEW), write secretary/blocked_report/$(DATE)_blocker_report.md and secretary/blocked_report/$(DATE)_blocker_report.json, then run python secretary/block_report_validator.py secretary/blocked_report/$(DATE)_blocker_report.json and summarize counts.

.PHONY: help check-prereqs run-agent agent-run validate-today print-config update-codex

help:
	@echo "Secretary Agent - blocked/to-review report preparation"
	@echo ""
	@echo "Targets:"
	@echo "  make run-agent               Run Codex agent using secretary instructions"
	@echo "  make agent-run               Alias for run-agent"
	@echo "  make validate-today          Validate $(DATE)_blocker_report.json"
	@echo "  make print-config            Show resolved paths and settings"
	@echo ""
	@echo "Options:"
	@echo "  DATE=YYYY-MM-DD              Override report date (default: today)"
	@echo "  OUTPUT=<file>                Override output transcript filename"
	@echo "  SOURCE_BLOCKED=<dir>         Source directory for blocked submissions"
	@echo "  SOURCE_TO_REVIEW=<dir>       Source directory for to-review submissions"

check-prereqs:
	@command -v codex >/dev/null 2>&1 || { echo "ERROR: codex CLI not found in PATH"; exit 1; }
	@command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found in PATH"; exit 1; }
	@test -f "$(INSTRUCTIONS)" || { echo "ERROR: missing $(INSTRUCTIONS)"; exit 1; }
	@test -f "$(VALIDATOR)" || { echo "ERROR: missing $(VALIDATOR)"; exit 1; }
	@test -f "$(JOURNAL_HELPER)" || { echo "ERROR: missing $(JOURNAL_HELPER)"; exit 1; }
	@mkdir -p "$(REPORT_DIR)"
	@echo "Prereqs: OK"

run-agent: check-prereqs
	rm -f "$(OUTPATH)"
	@TS=$$(date +%Y-%m-%d_%H%M%S); \
	python3 "$(JOURNAL_HELPER)" --dir "$(SECRETARY_DIR)" create --ts "$$TS"; \
	codex exec \
	  -C "$(REPO_ROOT)" \
	  -s workspace-write \
	  -c approval_policy=never \
	  -o "$(OUTPATH)" \
	  "$(PROMPT)"; \
	python3 "$(JOURNAL_HELPER)" --dir "$(SECRETARY_DIR)" append-agent --ts "$$TS" --cmd "make -C secretary run-agent DATE=$(DATE)" --output-file "$(OUTPATH)"; \
	echo "--- validating today's JSON report ---"; \
	python3 "$(JOURNAL_HELPER)" --dir "$(SECRETARY_DIR)" append-commands --ts "$$TS" --cmd "python3 $(VALIDATOR) $(REPORT_DIR)/$(DATE)_blocker_report.json" --run -- python3 "$(VALIDATOR)" "$(REPORT_DIR)/$(DATE)_blocker_report.json"; \
	echo "--- final output written to $(OUTPATH) ---"; \
	cat "$(OUTPATH)"

agent-run: run-agent

validate-today:
	python3 "$(VALIDATOR)" "$(REPORT_DIR)/$(DATE)_blocker_report.json"

print-config:
	@echo "SECRETARY_DIR=$(SECRETARY_DIR)"
	@echo "REPO_ROOT=$(REPO_ROOT)"
	@echo "INSTRUCTIONS=$(INSTRUCTIONS)"
	@echo "VALIDATOR=$(VALIDATOR)"
	@echo "REPORT_DIR=$(REPORT_DIR)"
	@echo "DATE=$(DATE)"
	@echo "OUTPATH=$(OUTPATH)"
	@echo "SOURCE_BLOCKED=$(SOURCE_BLOCKED)"
	@echo "SOURCE_TO_REVIEW=$(SOURCE_TO_REVIEW)"

update-codex:
	brew update && brew upgrade codex
	@echo "---"
	codex --version
