.PHONY: install demo validate-sample

install:
	@echo "No package install step required for this Python-based example."
	@python3 --version >/dev/null
	@echo "Python is available."

demo:
	@make -C triage_bot env_setup
	@make -C triage_bot triage-dry date=2026-01-15 skip_repos=1

validate-sample:
	@python3 secretary/block_report_validator.py secretary/blocked_report/2026-01-15_blocker_report.json
