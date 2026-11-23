COMPOSE ?= docker compose
PROFILES := --profile examples --profile caddy

.PHONY: setup up up-examples up-caddy down down-v logs ps config reset doctor

setup:
	@mkdir -p data/prometheus data/grafana data/loki data/alloy
	@chmod 0777 data/prometheus data/grafana data/loki data/alloy

up: setup
	$(COMPOSE) up -d

up-examples: setup
	@$(COMPOSE) --profile caddy stop caddy >/dev/null 2>&1 || true
	$(COMPOSE) --profile examples up -d

up-caddy: setup
	@$(COMPOSE) --profile examples stop nginx nginx-exporter >/dev/null 2>&1 || true
	$(COMPOSE) --profile caddy up -d

down:
	$(COMPOSE) $(PROFILES) down

down-v:
	$(COMPOSE) $(PROFILES) down -v

logs:
	$(COMPOSE) $(PROFILES) logs -f

ps:
	$(COMPOSE) $(PROFILES) ps

config:
	$(COMPOSE) $(PROFILES) config

reset: down
	@rm -rf data/prometheus data/grafana data/loki data/alloy
	@mkdir -p data/prometheus data/grafana data/loki data/alloy

doctor:
	@echo "== environment check =="
	@if docker info --format '{{.SecurityOptions}}' 2>/dev/null | grep -q rootless; then \
		echo "mode: rootless"; \
	else \
		echo "mode: rootful"; \
	fi
	@if [ -S "$${DOCKER_SOCKET:-/var/run/docker.sock}" ]; then \
		echo "socket: $${DOCKER_SOCKET:-/var/run/docker.sock} OK"; \
	else \
		echo "socket: $${DOCKER_SOCKET:-/var/run/docker.sock} NOT FOUND"; \
		echo '  rootless 环境请在 .env 设置 DOCKER_SOCKET=$$XDG_RUNTIME_DIR/docker.sock'; \
	fi
