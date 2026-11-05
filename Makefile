.PHONY: install run run-prebuilt client fmt clean

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
HOST ?= 0.0.0.0
PORT ?= 8080

install:  ## Create venv and install deps
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "Done. Now: cp .env.example .env && edit it, then 'make run'."

run:  ## Start Nora (WebRTC) on $(HOST):$(PORT)
	$(PY) server/bot.py -t webrtc --host $(HOST) --port $(PORT)

run-prebuilt: run  ## Alias; the prebuilt UI lives at /client on the same server

client:  ## Serve the branded client (separate static server on :3000)
	$(PY) -m http.server 3000 --directory client

clean:
	rm -rf $(VENV) **/__pycache__
