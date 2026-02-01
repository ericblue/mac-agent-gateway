.PHONY: install-deps venv install dev run test lint format clean clean-all help \
	generate-api-key generate-signing-key sign-skills verify-skills release-tag release-retag \
	service-install service-uninstall service-start service-stop service-restart service-status service-logs \
	openclaw-skill-install openclaw-skill-uninstall openclaw-skill-config openclaw-skill-check \
	claude-skill-install claude-skill-uninstall claude-skill-check

# Virtual environment
VENV = .venv
VENV_BIN = $(VENV)/bin
PYTHON = $(VENV_BIN)/python
PIP = $(VENV_BIN)/pip
UVICORN = $(VENV_BIN)/uvicorn
PYTEST = $(VENV_BIN)/pytest
RUFF = $(VENV_BIN)/ruff

# launchd paths
PLIST_NAME = com.ericblue.mag.plist
PLIST_SRC = launchd/$(PLIST_NAME)
PLIST_DEST = $(HOME)/Library/LaunchAgents/$(PLIST_NAME)

# Claude Code skill paths
CLAUDE_SKILLS_DIR = $(HOME)/.claude/skills
SKILLS = mag-reminders mag-messages

# Default target
help:
	@echo "Mac Agent Gateway (MAG) - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install-deps    Install CLI dependencies (remindctl, imsg)"
	@echo "  make venv            Create Python virtual environment"
	@echo "  make install         Install MAG and Python dependencies"
	@echo "  make generate-api-key  Generate a secure random API key"
	@echo ""
	@echo "Development:"
	@echo "  make dev           Run with auto-reload (development mode)"
	@echo "  make run           Run in production mode"
	@echo "  make test          Run tests"
	@echo "  make lint          Run linter (ruff check)"
	@echo "  make format        Format code (ruff format)"
	@echo ""
	@echo "Skill Signing:"
	@echo "  make generate-signing-key  Generate Ed25519 keypair for signing skills"
	@echo "  make sign-skills           Sign all SKILL.md files"
	@echo "  make verify-skills         Verify signatures on all SKILL.md files"
	@echo ""
	@echo "Release:"
	@echo "  make release-tag VERSION=X.Y.Z    Create and push a git tag for release"
	@echo "  make release-retag VERSION=X.Y.Z  Delete and recreate an existing tag"
	@echo ""
	@echo "Service (launchd):"
	@echo "  make service-install    Install launchd plist (edit first!)"
	@echo "  make service-uninstall  Remove launchd plist"
	@echo "  make service-start      Start the service"
	@echo "  make service-stop       Stop the service"
	@echo "  make service-restart    Restart the service"
	@echo "  make service-status     Check if service is running"
	@echo "  make service-logs       Tail the service logs"
	@echo ""
	@echo "Claude Code Skills:"
	@echo "  make claude-skill-install    Install all skills to ~/.claude/skills/"
	@echo "  make claude-skill-uninstall  Remove all skills from ~/.claude/skills/"
	@echo "  make claude-skill-check      Check if skills are installed"
	@echo ""
	@echo "OpenClaw Skills:"
	@echo "  Skill files go to:   ~/clawd/skills/ (OPENCLAW_SKILLS_DIR)"
	@echo "  Credentials go to:   ~/.clawdbot/clawdbot.json"
	@echo ""
	@echo "  make openclaw-skill-install    Copy SKILL.md files to skills dir"
	@echo "  make openclaw-skill-uninstall  Remove skill files"
	@echo "  make openclaw-skill-config MAG_URL=... MAG_API_KEY=...  Set credentials"
	@echo "  make openclaw-skill-check  MAG_URL=...                  Verify setup"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean         Remove build artifacts and caches"

# Generate a secure random API key
generate-api-key:
	@echo "Generating secure API key (48 characters)..."
	@KEY=$$(python3 -c "import secrets; print(secrets.token_urlsafe(36))"); \
	echo ""; \
	echo "Your new API key:"; \
	echo "  $$KEY"; \
	echo ""; \
	echo "Add to your .env file:"; \
	echo "  MAG_API_KEY=$$KEY"; \
	echo ""; \
	echo "Or export directly:"; \
	echo "  export MAG_API_KEY=$$KEY"

# ============================================================================
# Skill Signing
# ============================================================================

# Generate Ed25519 keypair for signing skills
# Keys are stored in ~/.mag/ (private key should be kept secret!)
generate-signing-key:
	@python3 scripts/sign_skill.py --generate-key

# Sign all SKILL.md files with the private key
# Run this before releases to ensure skills are signed
sign-skills:
	@if [ ! -f $(HOME)/.mag/signing_key.pem ]; then \
		echo "Error: No signing key found."; \
		echo "Run 'make generate-signing-key' first."; \
		exit 1; \
	fi
	python3 scripts/sign_skill.py skills/*/SKILL.md

# Verify signatures on all SKILL.md files
# Use this to check that skills have not been tampered with
verify-skills:
	@python3 -c "import cryptography" 2>/dev/null || { \
		echo "Error: cryptography library required for verification"; \
		echo ""; \
		echo "Install with one of:"; \
		echo "  pip install cryptography"; \
		echo "  pip install -e '.[signing]'"; \
		echo "  make install  # (includes cryptography in dev deps)"; \
		exit 1; \
	}
	python3 scripts/verify_skill.py skills/*/SKILL.md

# ============================================================================
# Release Management
# ============================================================================

# Create and push a git tag for release
# Usage: make release-tag VERSION=1.2.3
release-tag:
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION is required"; \
		echo "Usage: make release-tag VERSION=1.2.3"; \
		exit 1; \
	fi
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Error: Working directory is not clean"; \
		echo "Commit or stash your changes first"; \
		exit 1; \
	fi
	@if git rev-parse "v$(VERSION)" >/dev/null 2>&1; then \
		echo "Error: Tag v$(VERSION) already exists"; \
		exit 1; \
	fi
	@echo "Creating release v$(VERSION)..."
	@echo ""
	@echo "Pre-release checklist:"
	@echo "  1. Version updated in pyproject.toml and src/mag/__init__.py"
	@echo "  2. Skills signed with 'make sign-skills'"
	@echo "  3. Tests passing with 'make test'"
	@echo ""
	@read -p "Continue with tagging v$(VERSION)? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	git tag -a "v$(VERSION)" -m "Release v$(VERSION)"
	git push origin main
	git push origin "v$(VERSION)"
	@echo ""
	@echo "Release v$(VERSION) tagged and pushed!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Create GitHub release at:"
	@echo "     https://github.com/ericblue/mac-agent-gateway/releases/new?tag=v$(VERSION)"
	@echo "  2. Add release notes"

# Delete and recreate an existing git tag
# Usage: make release-retag VERSION=1.2.3
release-retag:
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION is required"; \
		echo "Usage: make release-retag VERSION=1.2.3"; \
		exit 1; \
	fi
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Error: Working directory is not clean"; \
		echo "Commit or stash your changes first"; \
		exit 1; \
	fi
	@if ! git rev-parse "v$(VERSION)" >/dev/null 2>&1; then \
		echo "Error: Tag v$(VERSION) does not exist"; \
		echo "Use 'make release-tag VERSION=$(VERSION)' to create a new tag"; \
		exit 1; \
	fi
	@echo "Retagging release v$(VERSION)..."
	@echo ""
	@echo "This will DELETE and RECREATE tag v$(VERSION)"
	@echo "If a GitHub Release exists for this tag, you may need to update it manually."
	@echo ""
	@read -p "Continue with retagging v$(VERSION)? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	git tag -d "v$(VERSION)"
	git push origin --delete "v$(VERSION)" 2>/dev/null || echo "Remote tag not found (may not have been pushed)"
	git tag -a "v$(VERSION)" -m "Release v$(VERSION)"
	git push origin main
	git push origin "v$(VERSION)"
	@echo ""
	@echo "Release v$(VERSION) retagged and pushed!"

# Install CLI dependencies via Homebrew
install-deps:
	@echo "Installing remindctl and imsg..."
	brew install steipete/tap/remindctl
	brew install steipete/tap/imsg
	@echo "Done. Grant Reminders and Messages permissions when prompted."

# Create virtual environment
venv:
	@if [ ! -d $(VENV) ]; then \
		echo "Creating virtual environment..."; \
		python3 -m venv $(VENV); \
		echo "Virtual environment created at $(VENV)"; \
	else \
		echo "Virtual environment already exists at $(VENV)"; \
	fi

# Install Python package in development mode (creates venv if needed)
install: venv
	@echo "Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@echo ""
	@echo "Installation complete!"
	@echo "Run 'make dev' to start the development server."

# Run in development mode with auto-reload
dev: venv
	@if [ ! -f $(UVICORN) ]; then \
		echo "Error: Dependencies not installed. Run 'make install' first."; \
		exit 1; \
	fi
	@if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
	if [ -z "$$MAG_API_KEY" ]; then \
		echo "Error: MAG_API_KEY not set (check .env or environment)"; \
		echo "Run: make generate-api-key"; \
		exit 1; \
	fi; \
	case "$$(echo $$MAG_API_KEY | tr '[:upper:]' '[:lower:]')" in \
		your-secret-api-key-here|your-secret-api-key|changeme|secret|password|test-key|demo-key) \
			echo "============================================================"; \
			echo "ERROR: MAG_API_KEY is a placeholder/insecure value"; \
			echo ""; \
			echo "To fix:"; \
			echo "  1. Run: make generate-api-key"; \
			echo "  2. Update MAG_API_KEY in your .env file"; \
			echo "============================================================"; \
			exit 1; \
			;; \
	esac; \
	$(UVICORN) mag.main:app --reload --host $${MAG_HOST:-127.0.0.1} --port $${MAG_PORT:-8123}

# Run in production mode
run: venv
	@if [ ! -f $(PYTHON) ]; then \
		echo "Error: Dependencies not installed. Run 'make install' first."; \
		exit 1; \
	fi
	@if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
	if [ -z "$$MAG_API_KEY" ]; then \
		echo "Error: MAG_API_KEY not set (check .env or environment)"; \
		echo "Run: make generate-api-key"; \
		exit 1; \
	fi; \
	case "$$(echo $$MAG_API_KEY | tr '[:upper:]' '[:lower:]')" in \
		your-secret-api-key-here|your-secret-api-key|changeme|secret|password|test-key|demo-key) \
			echo "============================================================"; \
			echo "ERROR: MAG_API_KEY is a placeholder/insecure value"; \
			echo ""; \
			echo "To fix:"; \
			echo "  1. Run: make generate-api-key"; \
			echo "  2. Update MAG_API_KEY in your .env file"; \
			echo "============================================================"; \
			exit 1; \
			;; \
	esac; \
	$(PYTHON) -m mag.main

# Run tests
test: venv
	@if [ ! -f $(PYTEST) ]; then \
		echo "Error: Dependencies not installed. Run 'make install' first."; \
		exit 1; \
	fi
	MAG_API_KEY=test-key $(PYTEST) -v

# Run linter
lint: venv
	@if [ ! -f $(RUFF) ]; then \
		echo "Error: Dependencies not installed. Run 'make install' first."; \
		exit 1; \
	fi
	$(RUFF) check src tests

# Format code
format: venv
	@if [ ! -f $(RUFF) ]; then \
		echo "Error: Dependencies not installed. Run 'make install' first."; \
		exit 1; \
	fi
	$(RUFF) format src tests

# Clean build artifacts (keeps venv)
clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache
	rm -rf src/*.egg-info
	rm -rf dist build
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# Clean everything including venv
clean-all: clean
	rm -rf $(VENV)
	@echo "Removed virtual environment. Run 'make install' to recreate."

# ============================================================================
# Claude Code Skill Management
# ============================================================================

# Check if skills are installed
claude-skill-check:
	@echo "Claude Code Skills Status"
	@echo "========================="
	@echo "Skills directory: $(CLAUDE_SKILLS_DIR)"
	@echo ""
	@for skill in $(SKILLS); do \
		echo "$$skill:"; \
		if [ -d $(CLAUDE_SKILLS_DIR)/$$skill ]; then \
			echo "  Status: INSTALLED"; \
			echo "  Location: $(CLAUDE_SKILLS_DIR)/$$skill"; \
		else \
			echo "  Status: NOT INSTALLED"; \
		fi; \
		echo ""; \
	done
	@echo "Run 'make claude-skill-install' to install all skills."

# Install all skills to Claude Code skills directory
# Verifies signatures before installing to ensure integrity
claude-skill-install:
	@echo "Installing MAG skills for Claude Code..."
	@echo ""
	@echo "Verifying skill signatures..."
	@if ! python3 -c "import cryptography" 2>/dev/null; then \
		echo ""; \
		echo "WARNING: cryptography library not installed - skipping verification"; \
		echo "To enable verification: pip install cryptography"; \
		echo ""; \
	else \
		python3 scripts/verify_skill.py skills/*/SKILL.md || { \
			echo ""; \
			echo "ERROR: Skill verification failed!"; \
			echo "Skills may be unsigned or tampered with."; \
			echo "Run 'make sign-skills' if you are the maintainer."; \
			exit 1; \
		}; \
	fi
	@echo ""
	@mkdir -p $(CLAUDE_SKILLS_DIR)
	@for skill in $(SKILLS); do \
		if [ ! -d skills/$$skill ]; then \
			echo "Error: Skill source not found at skills/$$skill"; \
			exit 1; \
		fi; \
		if [ -d $(CLAUDE_SKILLS_DIR)/$$skill ]; then \
			echo "Updating $$skill..."; \
			rm -rf $(CLAUDE_SKILLS_DIR)/$$skill; \
		else \
			echo "Installing $$skill..."; \
		fi; \
		cp -r skills/$$skill $(CLAUDE_SKILLS_DIR)/$$skill; \
		echo "  Installed to $(CLAUDE_SKILLS_DIR)/$$skill"; \
	done
	@echo ""
	@echo "Skills installed (verified)!"
	@echo ""
	@echo "Usage in Claude Code:"
	@echo "  1. Start claude in any directory"
	@echo "  2. Run: /add ~/.claude/skills/mag-reminders/SKILL.md"
	@echo "     Or:  /add ~/.claude/skills/mag-messages/SKILL.md"
	@echo "  3. Or ask: 'Use the mag-reminders skill to list my reminders'"
	@echo ""
	@echo "Don't forget to set MAG_URL and MAG_API_KEY environment variables!"

# Uninstall all skills from Claude Code skills directory
claude-skill-uninstall:
	@for skill in $(SKILLS); do \
		if [ -d $(CLAUDE_SKILLS_DIR)/$$skill ]; then \
			rm -rf $(CLAUDE_SKILLS_DIR)/$$skill; \
			echo "Removed $(CLAUDE_SKILLS_DIR)/$$skill"; \
		else \
			echo "$$skill not installed"; \
		fi; \
	done

# ============================================================================
# OpenClaw Skill Management
# ============================================================================
#
# OpenClaw uses two separate locations:
#   1. Skill files (SKILL.md) → ~/clawd/skills/ (workspace) or ~/.clawdbot/skills/ (global)
#   2. Config/credentials     → ~/.clawdbot/clawdbot.json
#
# Use openclaw-skill-install to copy skill files, then openclaw-skill-config
# to set up credentials in the config file.
# ============================================================================

# Skill files location (override with: make openclaw-skill-install OPENCLAW_SKILLS_DIR=~/my/path)
OPENCLAW_SKILLS_DIR ?= $(HOME)/clawd/skills

# Config file location
OPENCLAW_CONFIG_FILE = $(HOME)/.clawdbot/clawdbot.json

# Install skill files to OpenClaw skills directory
# Verifies signatures before installing to ensure integrity
openclaw-skill-install:
	@echo "Installing MAG skill files for OpenClaw..."
	@echo "Target directory: $(OPENCLAW_SKILLS_DIR)"
	@echo ""
	@echo "Verifying skill signatures..."
	@if ! python3 -c "import cryptography" 2>/dev/null; then \
		echo ""; \
		echo "WARNING: cryptography library not installed - skipping verification"; \
		echo "To enable verification: pip install cryptography"; \
		echo ""; \
	else \
		python3 scripts/verify_skill.py skills/*/SKILL.md || { \
			echo ""; \
			echo "ERROR: Skill verification failed!"; \
			echo "Skills may be unsigned or tampered with."; \
			echo "Run 'make sign-skills' if you are the maintainer."; \
			exit 1; \
		}; \
	fi
	@echo ""
	@mkdir -p $(OPENCLAW_SKILLS_DIR)
	@for skill in $(SKILLS); do \
		if [ ! -d skills/$$skill ]; then \
			echo "Error: Skill source not found at skills/$$skill"; \
			exit 1; \
		fi; \
		if [ -d $(OPENCLAW_SKILLS_DIR)/$$skill ]; then \
			echo "Updating $$skill..."; \
			rm -rf $(OPENCLAW_SKILLS_DIR)/$$skill; \
		else \
			echo "Installing $$skill..."; \
		fi; \
		cp -r skills/$$skill $(OPENCLAW_SKILLS_DIR)/$$skill; \
		echo "  -> $(OPENCLAW_SKILLS_DIR)/$$skill/SKILL.md"; \
	done
	@echo ""
	@echo "Skill files installed (verified)!"
	@echo ""
	@echo "Next: Configure credentials in ~/.clawdbot/clawdbot.json:"
	@echo "  make openclaw-skill-config MAG_URL=http://localhost:8124 MAG_API_KEY=your-key"

# Uninstall skill files from OpenClaw skills directory
openclaw-skill-uninstall:
	@for skill in $(SKILLS); do \
		if [ -d $(OPENCLAW_SKILLS_DIR)/$$skill ]; then \
			rm -rf $(OPENCLAW_SKILLS_DIR)/$$skill; \
			echo "Removed $(OPENCLAW_SKILLS_DIR)/$$skill"; \
		else \
			echo "$$skill not installed"; \
		fi; \
	done

# Configure ~/.clawdbot/clawdbot.json with MAG credentials
# Usage:
#   make openclaw-skill-config MAG_URL=http://localhost:8124 MAG_API_KEY=your-key
openclaw-skill-config:
	@if [ -z "$(MAG_URL)" ]; then \
		echo "Error: MAG_URL is required"; \
		echo "Example: make openclaw-skill-config MAG_URL=http://localhost:8124 MAG_API_KEY=..."; \
		exit 1; \
	fi
	@if [ -z "$(MAG_API_KEY)" ]; then \
		echo "Error: MAG_API_KEY is required"; \
		echo "Example: make openclaw-skill-config MAG_URL=http://localhost:8124 MAG_API_KEY=..."; \
		exit 1; \
	fi
	@python3 scripts/clawdbot_skill_config.py set --url "$(MAG_URL)" --api-key "$(MAG_API_KEY)"
	@echo "Note: restart/reload OpenClaw if it is running so it picks up the new config."

# Check skill configuration status
# Usage:
#   make openclaw-skill-check MAG_URL=http://localhost:8124
openclaw-skill-check:
	@echo "OpenClaw Skills Status"
	@echo "======================"
	@echo ""
	@echo "1. Skill Files"
	@echo "   Location: $(OPENCLAW_SKILLS_DIR)"
	@for skill in $(SKILLS); do \
		if [ -d $(OPENCLAW_SKILLS_DIR)/$$skill ]; then \
			echo "   $$skill: INSTALLED"; \
		else \
			echo "   $$skill: NOT INSTALLED (run: make openclaw-skill-install)"; \
		fi; \
	done
	@echo ""
	@echo "2. Credentials"
	@echo "   Location: $(OPENCLAW_CONFIG_FILE)"
	@if [ -z "$(MAG_URL)" ]; then \
		echo "   (pass MAG_URL=... to verify credentials)"; \
	else \
		python3 scripts/clawdbot_skill_config.py check --url "$(MAG_URL)"; \
	fi

# ============================================================================
# Service Management (launchd)
# ============================================================================

# Install the launchd plist (user must edit it first)
service-install:
	@if [ ! -f $(PLIST_SRC) ]; then \
		echo "Error: $(PLIST_SRC) not found"; \
		exit 1; \
	fi
	@echo "Installing launchd plist..."
	@echo "IMPORTANT: Edit the plist to set your paths and API key before starting!"
	@echo ""
	@mkdir -p $(PWD)/logs
	cp $(PLIST_SRC) $(PLIST_DEST)
	chmod 600 $(PLIST_DEST)
	@echo "Installed to $(PLIST_DEST)"
	@echo "Set permissions to 600 (owner read/write only)"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit $(PLIST_DEST)"
	@echo "     - Set WorkingDirectory to $(PWD)"
	@echo "     - Set PYTHONPATH to $(PWD)/src"
	@echo "     - Set Python path to $(PWD)/.venv/bin/python"
	@echo "     - Set MAG_API_KEY to a strong, random secret"
	@echo "     - Set log paths to $(PWD)/logs/mag.log and mag.error.log"
	@echo "  2. Run: make service-start"

# Uninstall the launchd plist
service-uninstall: service-stop
	@if [ -f $(PLIST_DEST) ]; then \
		rm $(PLIST_DEST); \
		echo "Removed $(PLIST_DEST)"; \
	else \
		echo "Plist not installed"; \
	fi

# Start the service
service-start:
	@if [ ! -f $(PLIST_DEST) ]; then \
		echo "Error: Service not installed. Run 'make service-install' first."; \
		exit 1; \
	fi
	launchctl load $(PLIST_DEST)
	@echo "Service started. Check status with: make service-status"

# Stop the service
service-stop:
	@if launchctl list | grep -q com.ericblue.mag; then \
		launchctl unload $(PLIST_DEST) 2>/dev/null || true; \
		echo "Service stopped"; \
	else \
		echo "Service not running"; \
	fi

# Restart the service
service-restart: service-stop service-start

# Check service status
service-status:
	@if launchctl list | grep -q com.ericblue.mag; then \
		echo "Service is running"; \
		launchctl list | grep com.ericblue.mag; \
		echo ""; \
		echo "Health check:"; \
		curl -s http://localhost:8123/health 2>/dev/null || echo "  Not responding (may still be starting)"; \
	else \
		echo "Service is not running"; \
	fi

# Tail the service logs
service-logs:
	@echo "=== MAG Logs (Ctrl+C to exit) ==="
	@echo "--- stdout: $(PWD)/logs/mag.log ---"
	@echo "--- stderr: $(PWD)/logs/mag.error.log ---"
	@echo ""
	@if [ ! -d $(PWD)/logs ]; then \
		echo "Log directory not found. Service may not have started yet."; \
		exit 1; \
	fi
	tail -f $(PWD)/logs/mag.log $(PWD)/logs/mag.error.log 2>/dev/null || \
		echo "Log files not found. Service may not have started yet."
