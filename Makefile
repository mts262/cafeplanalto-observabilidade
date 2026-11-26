TOPO    := topologia/cafeplanalto.clab.yml
BRIDGES := br-servicos br-gestao br-filial

.PHONY: build up down redeploy status check dns

build:
	docker build -t cafeplanalto/dns:latest imagens/dns
	docker build -t cafeplanalto/api:latest -f imagens/api/Dockerfile app/api
	docker build -t cafeplanalto/carga:latest imagens/carga
	docker build -t cafeplanalto/roteador:latest imagens/roteador

up: build
	@mkdir -p dados/prometheus dados/grafana dados/loki && chmod -R a+rwX dados
	@for b in $(BRIDGES); do sudo ip link add $$b type bridge 2>/dev/null || true; sudo ip link set $$b up; done
	sudo containerlab deploy -t $(TOPO)
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
