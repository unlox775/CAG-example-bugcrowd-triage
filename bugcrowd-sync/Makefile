.PHONY: sync install help sync-issue sync-force submissions-count check-env env_setup

# Default target
help:
	@echo "BugCrowd Sync Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  make env_setup         - Create .env from env.example"
	@echo "  make sync              - Run BugCrowd sync (uses env from .env if present)"
	@echo "  make sync-force        - Force deep sync on all submissions, ignoring skip optimization"
	@echo "  make sync-issue ISSUE_ID=xxx - Sync a single issue"
	@echo "  make submissions-count - Count submissions by date (requires SINCE= or BETWEEN=)"
	@echo "  make install           - Install Python dependencies"
	@echo "  make help              - Show this help message"

# Install Python dependencies
install:
	python3 -m pip install -r requirements.txt

env_setup:
	@if [ -f .env ]; then \
		echo ".env already exists"; \
	else \
		cp env.example .env; \
		echo "Created .env from env.example — edit with your credentials"; \
	fi

check-env:
	@bash -c 'if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
		if [ -z "$$BUGCROWD_AUTHHEADER" ] && { [ -z "$$BUGCROWD_USERNAME" ] || [ -z "$$BUGCROWD_PASSWORD" ]; }; then \
			echo "Error: set BUGCROWD_AUTHHEADER or BUGCROWD_USERNAME + BUGCROWD_PASSWORD"; \
			echo "Tip: run '\''make env_setup'\'' then edit .env"; \
			exit 1; \
		fi'

# Run BugCrowd sync (full output, no filtering)
sync: check-env
	@echo "Running BugCrowd sync..."
	@bash -c 'if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
		export PYTHONUNBUFFERED=1 && \
		python3 -u bin/bugcrowd_sync.py \
			--out data'

# Force deep sync on all submissions (useful for recovering from corruption)
sync-force: check-env
	@echo "Running BugCrowd sync (FORCE DEEP SYNC - ignoring skip optimization)..."
	@bash -c 'if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
		export PYTHONUNBUFFERED=1 && \
		python3 -u bin/bugcrowd_sync.py \
			--out data \
			--force-deep-sync'

# Count submissions by date range (reads .state/bugcrowd.json)
# Usage: make submissions-count SINCE=2026-01-01
#   or:  make submissions-count BETWEEN=2025-01-01,2026-01-01
submissions-count:
	@if [ -n "$(SINCE)" ]; then \
		python3 bin/submissions_count.py --since "$(SINCE)"; \
	elif [ -n "$(BETWEEN)" ]; then \
		python3 bin/submissions_count.py --between "$(BETWEEN)"; \
	else \
		echo "Error: Either SINCE=YYYY-MM-DD or BETWEEN=START,END is required"; \
		echo "  make submissions-count SINCE=2026-01-01"; \
		echo "  make submissions-count BETWEEN=2025-01-01,2026-01-01"; \
		exit 1; \
	fi

# Sync a single issue (for debugging/examination)
sync-issue: check-env
	@if [ -z "$(ISSUE_ID)" ]; then \
		echo "Error: ISSUE_ID is required. Usage: make sync-issue ISSUE_ID=xxx"; \
		exit 1; \
	fi
	@echo "Syncing single issue $(ISSUE_ID)..."
	@bash -c 'if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
		python3 bin/sync_single_issue.py "$(ISSUE_ID)" \
			--out data'
