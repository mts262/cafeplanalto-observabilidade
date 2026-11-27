TOPO    := topologia/cafeplanalto.clab.yml
BRIDGES := br-servicos br-gestao br-filial

.PHONY: build up down redeploy status check dns

build:
	docker build -t cafeplanalto/dns:latest imagens/dns
	docker build -t cafeplanalto/api:latest -f imagens/api/Dockerfile app/api
	docker build -t cafeplanalto/carga:latest imagens/carga
	docker build -t cafeplanalto/roteador:latest imagens/roteador

up: build
	@mkdir -p dados/prometheus dados/grafana dados/loki && sudo chmod 777 dados dados/prometheus dados/grafana dados/loki 2>/dev/null || true
	@for b in $(BRIDGES); do sudo ip link add $$b type bridge 2>/dev/null || true; sudo ip link set $$b up; done
	sudo containerlab deploy -t $(TOPO)
	$(MAKE) ips-extra
	$(MAKE) zabbix

down:
	sudo containerlab destroy -t $(TOPO) --cleanup
	@for b in $(BRIDGES); do sudo ip link del $$b 2>/dev/null || true; done

redeploy: down up

status:
	sudo containerlab inspect -t $(TOPO)

check:
	docker exec clab-cafeplanalto-cliente-carga traceroute 172.20.10.10

dns:
	docker exec clab-cafeplanalto-cliente-carga nslookup loja.cafeplanalto.lab

.PHONY: zabbix zabbix-status

zabbix:
	python3 zabbix/configurar.py

zabbix-status:
	python3 zabbix/configurar.py status

.PHONY: ips-extra

ips-extra:
	@for par in loki:172.20.99.23 alloy:172.20.99.28 nginx-exporter:172.20.99.27; do \
	  nome=$${par%%:*}; ip=$${par##*:}; \
	  pid=$$(docker inspect -f '{{.State.Pid}}' clab-cafeplanalto-$$nome); \
	  sudo nsenter -t $$pid -n ip addr add $$ip/24 dev eth1 2>/dev/null || true; \
	  sudo nsenter -t $$pid -n ip link set eth1 up; \
	  sudo nsenter -t $$pid -n ip route add 172.20.0.0/16 via 172.20.99.1 2>/dev/null || true; \
	  sudo nsenter -t $$pid -n ip route add 10.0.0.0/30 via 172.20.99.1 2>/dev/null || true; \
	done
