TOPO    := topologia/cafeplanalto.clab.yml
BRIDGES := br-servicos br-gestao br-filial

.PHONY: up down redeploy status check

up:
	@for b in $(BRIDGES); do sudo ip link add $$b type bridge 2>/dev/null || true; sudo ip link set $$b up; done
	sudo containerlab deploy -t $(TOPO)

down:
	sudo containerlab destroy -t $(TOPO) --cleanup
	@for b in $(BRIDGES); do sudo ip link del $$b 2>/dev/null || true; done

redeploy: down up

status:
	sudo containerlab inspect -t $(TOPO)

check:
	docker exec clab-cafeplanalto-cliente-carga traceroute 172.20.10.10
