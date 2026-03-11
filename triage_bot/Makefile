# Triage Bot Makefile
# Run Codex agent on pending analyze items in blocker reports.
#
# Usage:
#   make triage date=2026-02-05           # Process next one item
#   make triage date=2026-02-05 all=1     # Process all items
#   make triage date=2026-02-05 dry_run=1 # Print commands, don't run
#
#   make check_repos                      # Verify repos on correct branches
#   make up_to_date                       # git pull each repo (prompts first)
#   make up_to_date confirm=1             # Skip prompt

.PHONY: triage triage-dry revalidate check_repos up_to_date help env_setup

# report_date: required for triage (YYYY-MM-DD)
# all: set to 1 to process all items
# dry_run: set to 1 to print commands only
# confirm: set to 1 for up_to_date to skip prompt

help:
	@echo "Triage Bot — Codex-based security triage automation"
	@echo ""
	@echo "Targets:"
	@echo "  make triage date=YYYY-MM-DD     Run triage on next item (default: one)"
	@echo "  make triage date=YYYY-MM-DD all=1   Run triage on ALL items"
	@echo "  make triage date=YYYY-MM-DD dry_run=1   Dry run (print commands & prompt)"
	@echo "  make triage date=YYYY-MM-DD skip_repos=1   Skip repo branch check"
	@echo "  make triage-dry date=YYYY-MM-DD         Same as triage dry_run=1"
	@echo "  make revalidate date=YYYY-MM-DD         Re-run validation on all 'validated' runtimes, update to error if they fail"
	@echo "  make check_repos                Check configured analysis repos"
	@echo "  make up_to_date                 Update all repos (prompts first)"
	@echo "  make up_to_date confirm=1       Update repos without prompt"
	@echo "  make env_setup                  Create .env from env.example"
	@echo ""
	@echo "Requires: codex CLI (npm i -g @openai/codex)"

# Load .env if present
-include .env
export

triage:
	@if [ -z "$(date)" ]; then echo "Usage: make triage date=YYYY-MM-DD"; exit 1; fi
	@REPORT_DATE="$(date)"; \
	EXTRA=; [ -n "$(skip_repos)" ] && [ "$(skip_repos)" != "0" ] && EXTRA="--skip-repos-check"; \
	if [ -n "$(all)" ] && [ "$(all)" != "0" ]; then \
		python3 run_triage.py --date "$$REPORT_DATE" --all $$EXTRA; \
	elif [ -n "$(dry_run)" ] && [ "$(dry_run)" != "0" ]; then \
		python3 run_triage.py --date "$$REPORT_DATE" --dry-run $$EXTRA; \
	else \
		python3 run_triage.py --date "$$REPORT_DATE" $$EXTRA; \
	fi

# Dry run: show command and full prompt, no Codex execution
triage-dry: dry_run = 1
triage-dry: triage

# Re-run validation on all agent runtimes that claim validation_status=validated.
# Updates the last runtime in-place (no new block) if validation fails.
revalidate:
	@if [ -z "$(date)" ]; then echo "Usage: make revalidate date=YYYY-MM-DD"; exit 1; fi
	@python3 update_blocker_json.py revalidate --date "$(date)"

check_repos:
	@python3 check_repos.py

up_to_date:
	@echo "This will run 'git pull' in each configured repo."
	@if [ -z "$(confirm)" ] || [ "$(confirm)" = "0" ]; then \
		echo -n "Continue? [y/N] "; read -r ans; \
		if [ "$$ans" != "y" ] && [ "$$ans" != "Y" ]; then echo "Aborted."; exit 1; fi; \
	fi
	@python3 update_repos.py

env_setup:
	@if [ -f .env ]; then \
		echo ".env already exists"; \
	else \
		cp env.example .env; \
		echo "Created .env from env.example — edit with your paths"; \
	fi
