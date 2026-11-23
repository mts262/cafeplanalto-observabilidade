# Café Planalto: monitoramento e observabilidade

Laboratório virtual de uma torrefação fictícia (matriz + filial ligadas por WAN, com loja virtual), monitorado com **Zabbix** e **Prometheus + Grafana**. Trabalho prático da disciplina de Projeto e Administração de Redes (IFBA, Vitória da Conquista).

Autores: Matheus Pereira Rodrigues e Vinícius Ribeiro.

## Topologia

```
                      WAN 10.0.0.0/30
   r-matriz (.1) ======================= (.2) r-filial
    |      |                                    |
 eth2|   eth3|                               eth2|
    |      |                                    |
LAN Serviços        LAN Gerência           LAN Filial
172.20.10.0/24      172.20.99.0/24         172.20.20.0/24
 dns   .10           (Zabbix, Prometheus,   cliente-carga .20
 web   .20            Grafana, Loki:         sonda         .30
 api   .21            em construção)
 db    .22
```

Gerência fora de banda do Containerlab: `172.30.0.0/24` (eth0 de todos os nós). Serve só para administração. **A coleta de monitoramento nunca passa por ela.**

Rotas estáticas (definidas nos arquivos `topologia/configs/*/frr.conf` e nos `exec` da topologia):

| Equipamento | Destino | Próximo salto |
|---|---|---|
| r-matriz | 172.20.20.0/24 | 10.0.0.2 |
| r-filial | 172.20.10.0/24 e 172.20.99.0/24 | 10.0.0.1 |
| Hosts de cada LAN | 172.20.0.0/16 e 10.0.0.0/30 | gateway .1 da própria LAN |

## Requisitos

- Linux (Ubuntu/Debian) com 4 GB de RAM livres ou mais, ou Windows 11 com WSL2 e Ubuntu 24.04.
- Docker Engine, Docker Compose plugin, Containerlab, Git e Make.
- Acesso à internet na primeira subida (baixa as imagens).
- `python3` (o Ubuntu já traz; o `make zabbix` usa).

### Instalação no Ubuntu/Debian

```bash
sudo apt update && sudo apt install -y ca-certificates curl git make
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
sudo systemctl enable --now docker
curl -sL https://containerlab.dev/setup | sudo -E bash -s "all"
```

Depois, **feche e abra o terminal** (para o grupo `docker` valer) e confira:

```bash
docker run --rm hello-world
containerlab version
```

### Windows 11 (WSL2)

No PowerShell: `wsl --install -d Ubuntu-24.04`. Para limitar a memória, crie `C:\Users\SEU_USUARIO\.wslconfig` com:

```
[wsl2]
memory=8GB
processors=4
swap=4GB
```

Aplique com `wsl --shutdown` e siga a instalação do Ubuntu acima, **dentro do WSL**. Clone o repositório em `~/`, nunca em `/mnt/c/`.

## Subir e derrubar o ambiente

```bash
git clone https://github.com/mts262/cafeplanalto-observabilidade.git
cd cafeplanalto-observabilidade
make up
```

O `make up` constrói as imagens, cria as bridges no host e sobe a topologia. Pede a senha do `sudo`. Aguarde de 2 a 4 minutos: o final do `make up` espera o Zabbix ficar pronto e cadastra os hosts sozinho.

| Comando | O que faz |
|---|---|
| `make up` | Constrói as imagens e sobe o laboratório |
| `make down` | Destrói o laboratório e remove as bridges |
| `make redeploy` | `down` + `up` (use sempre que o computador reiniciar) |
| `make status` | Lista os contêineres e seus IPs |
| `make check` | `traceroute` da filial até a LAN Serviços |
| `make dns` | Resolve `loja.cafeplanalto.lab` a partir da filial |
| `make zabbix` | Cadastra grupo, hosts e templates no Zabbix pela API (o `make up` já chama) |
| `make zabbix-status` | Mostra disponibilidade e itens de cada host no Zabbix |

## Como verificar que funcionou

Todos os testes partem da **filial** (`cliente-carga`), atravessando a WAN:

```bash
# 14 contêineres de pé (7 da loja e da rede, 3 do Zabbix, 4 agentes)
docker ps --format '{{.Names}}' | wc -l

# Roteamento: deve passar por 172.20.20.1 e 10.0.0.1
make check

# DNS interno
docker exec clab-cafeplanalto-cliente-carga dig +short loja.cafeplanalto.lab

# Loja em três camadas: cria um pedido pelo nome
docker exec clab-cafeplanalto-cliente-carga wget -qO- --header='Content-Type: application/json' --post-data='{"produto_id":1,"quantidade":2}' http://loja.cafeplanalto.lab/pedidos

# Métricas e carga contínua (deve mostrar cerca de 10 req/s)
docker exec clab-cafeplanalto-cliente-carga wget -qO- http://api.cafeplanalto.lab:8000/metrics | grep http_requests_total
```

## A loja

| Componente | IP | Tecnologia |
|---|---|---|
| web | 172.20.10.20 | Nginx (proxy reverso, `stub_status` restrito à LAN Gerência) |
| api | 172.20.10.21 | Python + FastAPI |
| db | 172.20.10.22 | PostgreSQL 16 |
| dns | 172.20.10.10 | CoreDNS, zona `cafeplanalto.lab` |
| cliente-carga | 172.20.20.20 | k6, 10 req/s contínuos (80% catálogo, 20% pedidos) |

Endpoints da API: `GET /produtos`, `POST /pedidos`, `GET /health`, `GET /metrics`, `GET/POST /admin/caos`.

### Injeção de falhas na aplicação

```bash
# API lenta (800 ms)
docker exec clab-cafeplanalto-cliente-carga wget -qO- --header='Content-Type: application/json' --post-data='{"latencia_ms":800}' http://api.cafeplanalto.lab:8000/admin/caos

# 20% de erros 500
docker exec clab-cafeplanalto-cliente-carga wget -qO- --header='Content-Type: application/json' --post-data='{"taxa_erro":0.2}' http://api.cafeplanalto.lab:8000/admin/caos

# Desligar o caos
docker exec clab-cafeplanalto-cliente-carga wget -qO- --header='Content-Type: application/json' --post-data='{"latencia_ms":0,"taxa_erro":0}' http://api.cafeplanalto.lab:8000/admin/caos
```

O `/health`, o `/metrics` e o `/admin/caos` não sofrem caos.

## Zabbix (rede e infraestrutura)

Versão **Zabbix 8.0 LTS** (imagens `alpine-8.0-latest`), em três contêineres na LAN Gerência:

| Contêiner | IP | Função |
|---|---|---|
| zabbix-server | 172.20.99.10 | Servidor |
| zabbix-web | 172.20.99.11 | Frontend, publicado em `http://localhost:8080` |
| zabbix-db | 172.20.99.12 | PostgreSQL do Zabbix |

Acesso: `http://localhost:8080`, usuário `Admin`, senha `zabbix` (padrão do Zabbix; o ambiente é local e descartável).

**Agentes.** Cada host da matriz (dns, web, api, db) tem um contêiner `agent-<host>` com o Zabbix Agent 2 oficial, na mesma pilha de rede do host (`network-mode: container:<host>`). O agente responde no IP do próprio host, e o servidor coleta pela rede de dados (eth1), atravessando o r-matriz, nunca pela gerência fora de banda. Limitação: a CPU e a memória lidas pelo agente são as da VM inteira, e não as de cada contêiner.

**Configuração como código.** Tudo o que se cadastra no Zabbix está em `zabbix/configurar.py`, que usa a API. Ele é idempotente e roda no final do `make up` (ou sozinho, com `make zabbix`). Cadastra o grupo `Cafe Planalto`, os hosts com templates e macros, e desativa o host padrão "Zabbix server":

| Host | IP | Templates |
|---|---|---|
| dns | 172.20.10.10 | Linux by Zabbix agent |
| web | 172.20.10.20 | Linux by Zabbix agent, Nginx by Zabbix agent |
| api | 172.20.10.21 | Linux by Zabbix agent |
| db | 172.20.10.22 | Linux by Zabbix agent, PostgreSQL by Zabbix agent 2 |

**Importante:** o banco do Zabbix é recriado a cada `make up`. O que for configurado só pela interface se perde. Mudanças permanentes devem ir para o `configurar.py`.

Para verificar:

```bash
make zabbix-status
```

O esperado é os quatro hosts `DISPONIVEL`. Os itens "não suportados" `Number of installed packages` e `r_await`/`w_await` dos discos são esperados em contêineres e podem ser ignorados.

## Estrutura do repositório

```
topologia/   topologia Containerlab e configs dos roteadores (FRR)
imagens/     Dockerfiles (dns, api, carga) e config do Nginx
app/         código da API e SQL do banco
dns/         Corefile e zona cafeplanalto.lab
carga/       script k6 e entrypoint
zabbix/      script de configuração do Zabbix pela API (configurar.py)
prometheus/  prometheus.yml, regras, alertmanager  (em construção)
grafana/     provisionamento e dashboards          (em construção)
loki/        config do Loki e do coletor de logs   (em construção)
scripts/     injeção de falhas e utilitários       (em construção)
docs/        diagrama, endereçamento e relatório   (em construção)
```

## Problemas comuns

- **Roteadores não aparecem em `docker ps`:** o WSL ou o Docker foi reiniciado. Rode `make redeploy`.
- **`permission denied` no Docker:** abra um terminal novo depois do `usermod`.
- **Pasta `topologia/clab-cafeplanalto/`:** é gerada a cada deploy e está no `.gitignore`. Não versione.
- **Mac com Apple Silicon:** as imagens usadas têm versão arm64.
- **Porta 8080 ocupada:** o frontend do Zabbix usa a 8080 do host. Confira com `ss -ltn | grep 8080` antes do `make up`.
- **`make zabbix` falhou por tempo esgotado:** o Zabbix leva alguns minutos para inicializar o banco na primeira subida. Rode `make zabbix` de novo; ele é idempotente.
- **Hosts com interface "desconhecida" logo após o `make up`:** aguarde de 1 a 2 minutos pela primeira coleta.
