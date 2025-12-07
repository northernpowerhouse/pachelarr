SHELL := /bin/bash

.PHONY: install-dev test docker-build-dev docker-test

install-dev:
	@if command -v poetry >/dev/null 2>&1; then \
		poetry install; \
	else \
		python3 -m pip install --user -r requirements-dev.txt; \
	fi

test:
	python3 -m pytest -q -s

docker-build-dev:
	docker compose build --build-arg INSTALL_DEV_DEPS=true

docker-test:
	docker compose up --build -d pachelarr && docker compose exec pachelarr python3 -m pytest -q -s || docker compose down
