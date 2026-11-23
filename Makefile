COMPOSE ?= docker compose
PROFILES := --profile examples --profile caddy

.PHONY: setup up up-examples up-caddy down down-v logs ps config reset

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
