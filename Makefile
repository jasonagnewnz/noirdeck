.PHONY: venv dev test frontend build run mine overnight install-service status

VENV=.venv
PY=$(VENV)/bin/python
PIP=$(VENV)/bin/pip

venv:
	python3 -m venv $(VENV)
	$(PIP) install -q -U pip
	$(PIP) install -q -r backend/requirements.txt

test:
	cd backend && ../$(PY) -m pytest -q

frontend:
	cd frontend && npm install --no-fund --no-audit && npm run build

build: venv frontend test

# Foreground dev run (backend serves built SPA)
run:
	$(PY) -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $${NOIRDECK_PORT:-4747}

# Heuristic mining now (no LLM, no egress)
mine:
	cd backend && ../$(PY) -m app.miner.cli heuristic

# Overnight queue runner once (requires NOIRDECK_OVERNIGHT_ARMED=true)
overnight:
	cd backend && ../$(PY) -m app.overnight --once

install-service:
	@echo "Installs systemd USER units (noirdeck.service, noirdeck-mine.timer, noirdeck-overnight.timer)."
	@echo "Review ops/*.service ops/*.timer first. Then:"
	@echo "  mkdir -p ~/.config/systemd/user && cp ops/noirdeck*.{service,timer} ~/.config/systemd/user/"
	@echo "  systemctl --user daemon-reload && systemctl --user enable --now noirdeck.service"
	@echo "Timers are opt-in: systemctl --user enable --now noirdeck-mine.timer noirdeck-overnight.timer"

status:
	@curl -s http://127.0.0.1:$${NOIRDECK_PORT:-4747}/api/health || echo "not running"
