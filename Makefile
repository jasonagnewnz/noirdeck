.PHONY: venv dev test frontend build run mine overnight units install-service status bundle wheel clean-dist

VENV=.venv
PY=$(VENV)/bin/python
PIP=$(VENV)/bin/pip
# Where this clone actually lives, as a systemd path (%h when under $HOME).
# ops/*.service ship with the default ~/noirdeck path for a public checkout.
UNIT_ROOT=$(shell pwd | sed "s|^$(HOME)|%h|")

venv:
	python3 -m venv $(VENV)
	$(PIP) install -q -U pip
	$(PIP) install -q -r backend/requirements.txt

test:
	cd backend && ../$(PY) -m pytest -q

# Run the suite the way CI will actually see it: a scratch HOME with no ~/.claude,
# and no `claude`/`ollama` on PATH. Three CI failures in a row came from tests that
# quietly assumed this machine — an existing config dir, a home-relative cwd, an
# installed CLI. All three passed locally. Run this before pushing, not after.
test-ci-env:
	@d=$$(mktemp -d); \
	HOME=$$d PATH=/usr/local/bin:/usr/bin:/bin $(PY) -m pytest backend -q; \
	rc=$$?; rm -rf $$d; exit $$rc

frontend:
	cd frontend && npm install --no-fund --no-audit && npm run build

build: venv frontend test

# Foreground dev run (backend serves built SPA)
run:
	$(PY) -m uvicorn noirdeck.main:app --app-dir backend --host 127.0.0.1 --port $${NOIRDECK_PORT:-4747}

# Heuristic mining now (no LLM, no egress)
mine:
	cd backend && ../$(PY) -m noirdeck.miner.cli heuristic

# Overnight queue runner once (requires NOIRDECK_OVERNIGHT_ARMED=true)
overnight:
	cd backend && ../$(PY) -m noirdeck.overnight --once

# --- distribution ---------------------------------------------------------
# The wheel carries the built SPA inside the package, so an installed copy has
# no repo to serve from. `bundle` is the copy step; `wheel` is the release build.
bundle: frontend
	rm -rf backend/noirdeck/web
	cp -r frontend/dist backend/noirdeck/web

wheel: bundle
	$(PY) -m pip install -q -U build
	$(PY) -m build
	@echo "built:" && ls -1 dist/

clean-dist:
	rm -rf dist backend/noirdeck/web

units:
	@mkdir -p dist/units
	@for f in ops/noirdeck*.service ops/noirdeck*.timer; do \
	  sed "s|%h/noirdeck|$(UNIT_ROOT)|g" "$$f" > "dist/units/$$(basename $$f)"; \
	done
	@echo "Units generated for THIS clone ($(UNIT_ROOT)) in dist/units/:"
	@grep -h '^ExecStart=' dist/units/*.service | sed 's/^/  /'

install-service: units
	@echo ""
	@echo "The units in ops/ target the default clone path (~/noirdeck); dist/units/"
	@echo "has them rewritten for this checkout. Installing copies files OUT of the"
	@echo "repo, so a later rename in the tree will NOT reach them — re-run this"
	@echo "target after any move or package rename."
	@echo ""
	@echo "  mkdir -p ~/.config/systemd/user && cp dist/units/* ~/.config/systemd/user/"
	@echo "  systemctl --user daemon-reload && systemctl --user enable --now noirdeck.service"
	@echo "Timers are opt-in: systemctl --user enable --now noirdeck-mine.timer noirdeck-overnight.timer"
	@echo "Verify after installing: systemctl --user list-timers 'noirdeck-*'"

status:
	@curl -s http://127.0.0.1:$${NOIRDECK_PORT:-4747}/api/health || echo "not running"
