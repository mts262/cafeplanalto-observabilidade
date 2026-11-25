
#!/usr/bin/env python3
"""Configura o Zabbix pela API: hosts, templates, cenario web e triggers."""

import json
import sys
import time
import urllib.request

URL = "http://localhost:8080/api_jsonrpc.php"
USUARIO = "Admin"
SENHA = "zabbix"
GRUPO = "Cafe Planalto"

NGINX = {
    "{$NGINX.STUB_STATUS.HOST}": "127.0.0.1",
    "{$NGINX.STUB_STATUS.PATH}": "stub_status",
}

PG = {
    "{$PG.USER}": "loja",
    "{$PG.PASSWORD}": "loja123",
    "{$PG.DATABASE}": "loja",
}

LINUX = "Linux by Zabbix agent"
NETDEV = "Network Generic Device by SNMP"
ICMP = "ICMP Ping"

SNMPM = {"{$SNMP_COMMUNITY}": "cafeplanalto"}

HOSTS = [
    {
        "host": "dns",
        "ip": "172.20.10.10",
        "templates": [LINUX],
        "macros": {},
    },
    {
        "host": "web",
        "ip": "172.20.10.20",
        "templates": [LINUX, "Nginx by Zabbix agent"],
        "macros": NGINX,
    },
    {
        "host": "api",
        "ip": "172.20.10.21",
        "templates": [LINUX],
        "macros": {},
    },
    {
        "host": "db",
        "ip": "172.20.10.22",
        "templates": [LINUX, "PostgreSQL by Zabbix agent 2"],
        "macros": PG,
    },
    {
        "host": "r-matriz",
        "ip": "172.20.99.1",
        "snmp": True,
        "templates": [NETDEV],
        "macros": SNMPM,
    },
    {
        "host": "r-filial",
        "ip": "10.0.0.2",
        "snmp": True,
        "templates": [NETDEV],
        "macros": SNMPM,
    },
    {
        "host": "cliente-carga",
        "ip": "172.20.20.20",
        "templates": [ICMP],
        "macros": {},
    },
]

token = None


# ---------------------------------------------------------------------
# API DO ZABBIX
# ---------------------------------------------------------------------

def api(metodo, params=None):
    corpo = {
        "jsonrpc": "2.0",
        "method": metodo,
        "params": params if params is not None else {},
        "id": 1,
    }

    cabecalho = {"Content-Type": "application/json-rpc"}

    if token:
        cabecalho["Authorization"] = "Bearer " + token

    requisicao = urllib.request.Request(
        URL,
        json.dumps(corpo).encode(),
        cabecalho,
    )

    with urllib.request.urlopen(requisicao, timeout=30) as resposta:
        resultado = json.load(resposta)

    if "error" in resultado:
        erro = resultado["error"]
        raise RuntimeError(
            f"{metodo}: {erro.get('message')} {erro.get('data')}"
        )

    return resultado["result"]


def esperar_login():
    global token

    ultimo_erro = ""
    limite = time.time() + 300

    while time.time() < limite:
        try:
            token = None
            token = api(
                "user.login",
                {
                    "username": USUARIO,
                    "password": SENHA,
                },
            )
            return

        except Exception as erro:
            ultimo_erro = str(erro)
            print("Aguardando API do Zabbix:", ultimo_erro)
            time.sleep(5)

    sys.exit(f"Zabbix nao ficou pronto em 5 minutos: {ultimo_erro}")


def id_host(nome):
    resultado = api(
        "host.get",
        {
            "output": ["hostid"],
            "filter": {"host": [nome]},
        },
    )

    if not resultado:
        sys.exit(f"Host {nome} nao cadastrado")

    return resultado[0]["hostid"]


# ---------------------------------------------------------------------
# Z5 E Z6: CENARIO WEB E TRIGGERS
# ---------------------------------------------------------------------

LOJA = "Loja"
LOJA_URL = "http://loja.cafeplanalto.lab"

SERVICOS = [
    (
        "web",
        "Porta 80 (Nginx)",
        "net.tcp.service[tcp,127.0.0.1,80]",
        "Nginx",
    ),
    (
        "api",
        "Porta 8000 (API)",
        "net.tcp.service[tcp,127.0.0.1,8000]",
        "API",
    ),
    (
        "db",
        "Porta 5432 (PostgreSQL)",
        "net.tcp.service[tcp,127.0.0.1,5432]",
        "PostgreSQL",
    ),
    (
        "dns",
        "Porta 53 (CoreDNS)",
        "net.tcp.service[tcp,127.0.0.1,53]",
        "CoreDNS",
    ),
]

T_MATRIZ = "Roteador r-matriz inacessivel (ICMP)"
T_WAN = "Enlace WAN fora: r-filial inacessivel (ICMP)"
T_WAN_RUIM = "Enlace WAN degradado (latencia > 150 ms ou perda > 2%)"
T_HOST = "Host indisponivel (agente sem resposta)"
T_LOJA = "Loja fora do ar (cenario web falhou)"
T_CARGA = "Host cliente-carga inacessivel (ICMP)"
CPU = "CPU alta (media > 80% em 5 min)"

# (host, nome, expressao, severidade, dependencias)
# A ordem e importante: a dependencia deve existir primeiro.

TRIGGERS = [
    (
        "r-matriz",
        T_MATRIZ,
        "max(/r-matriz/icmpping,#3)=0",
        4,
        [],
    ),
    (
        "r-filial",
        T_WAN,
        "max(/r-filial/icmpping,#3)=0",
        5,
        [("r-matriz", T_MATRIZ)],
    ),
    (
        "r-filial",
        T_WAN_RUIM,
        "avg(/r-filial/icmppingsec,#3)>0.15 or avg(/r-filial/icmppingloss,#3)>2",
        3,
        [("r-filial", T_WAN)],
    ),
    (
        "cliente-carga",
        T_CARGA,
        "max(/cliente-carga/icmpping,#3)=0",
        4,
        [("r-filial", T_WAN)],
    ),
]

TRIGGERS += [
    (
        host,
        T_HOST,
        f"nodata(/{host}/agent.ping,3m)=1",
        4,
        [("r-matriz", T_MATRIZ)],
    )
    for host in ("dns", "web", "api", "db")
]

TRIGGERS += [
    (
        host,
        f"Servico parado: {nome}",
        f"max(/{host}/{chave},#2)=0",
        4,
        [(host, T_HOST)],
    )
    for host, _, chave, nome in SERVICOS
]

TRIGGERS += [
    (
        host,
        CPU,
        f"avg(/{host}/system.cpu.util,5m)>80",
        2,
        [(host, T_HOST)],
    )
    for host in ("dns", "web", "api", "db")
]

TRIGGERS += [
    (
        "web",
        T_LOJA,
        f"last(/web/web.test.fail[{LOJA}])<>0",
        5,
        [("r-matriz", T_MATRIZ)],
    )
]


def itens_de_servico():
    """Cria itens que verificam se as portas dos servicos respondem."""

    for host, nome, chave, _ in SERVICOS:
        hid = id_host(host)

        existentes = api(
            "item.get",
            {
                "hostids": hid,
                "filter": {"key_": chave},
                "output": ["itemid"],
            },
        )

        if existentes:
            continue

        interfaces = api(
            "hostinterface.get",
            {
                "hostids": hid,
                "filter": {"type": 1},
            },
        )

        if not interfaces:
            print(f"ERRO: interface de agente nao encontrada em {host}")
            continue

        api(
            "item.create",
            {
                "name": f"Servico: {nome}",
                "key_": chave,
                "hostid": hid,
                "type": 0,
                "value_type": 3,
                "delay": "30s",
                "interfaceid": interfaces[0]["interfaceid"],
            },
        )

        print("Item criado:", host, chave)


def cenario_web():
    """Z5: cenario com dois passos, catalogo e criacao de pedido."""

    hid = id_host("web")

    passos = [
        {
            "name": "Abrir catalogo",
            "no": 1,
            "url": f"{LOJA_URL}/produtos",
            "status_codes": "200",
            "required": "Cafe",
            "timeout": "10s",
        },
        {
            "name": "Criar pedido",
            "no": 2,
            "url": f"{LOJA_URL}/pedidos",
            "posts": '{"produto_id": 1, "quantidade": 1}',
            "headers": [
                {
                    "name": "Content-Type",
                    "value": "application/json",
                }
            ],
            "status_codes": "201",
            "required": "produto_id",
            "timeout": "10s",
        },
    ]

    existente = api(
        "httptest.get",
        {
            "hostids": hid,
            "filter": {"name": LOJA},
            "output": ["httptestid", "name"],
        },
    )

    dados = {
        "name": LOJA,
        "delay": "30s",
        "retries": 1,
        "steps": passos,
    }

    if existente:
        dados["httptestid"] = existente[0]["httptestid"]
        api("httptest.update", dados)
        print("Cenario web atualizado:", LOJA)
    else:
        dados["hostid"] = hid
        api("httptest.create", dados)
        print("Cenario web criado:", LOJA)


def triggers():
    """Z6: cria ou atualiza triggers com suas dependencias."""

    ids = {}
    configuradas = 0
    falhas = 0

    def achar(host, nome):
        chave = (host, nome)

        if chave not in ids:
            resultado = api(
                "trigger.get",
                {
                    "hostids": id_host(host),
                    "output": ["triggerid"],
                    "filter": {"description": nome},
                },
            )

            if not resultado:
                sys.exit(
                    f"Trigger '{nome}' de {host} nao existe "
                    "e e necessaria como dependencia"
                )

            ids[chave] = resultado[0]["triggerid"]

        return ids[chave]

    for host, nome, expressao, prioridade, dependencias in TRIGGERS:
        try:
            deps = [
                {"triggerid": achar(host_dep, nome_dep)}
                for host_dep, nome_dep in dependencias
            ]

            existente = api(
                "trigger.get",
                {
                    "hostids": id_host(host),
                    "output": ["triggerid"],
                    "filter": {"description": nome},
                },
            )

            if existente:
                trigger_id = existente[0]["triggerid"]

                api(
                    "trigger.update",
                    {
                        "triggerid": trigger_id,
                        "expression": expressao,
                        "priority": prioridade,
                        "dependencies": deps,
                    },
                )

                ids[(host, nome)] = trigger_id

            else:
                criada = api(
                    "trigger.create",
                    {
                        "description": nome,
                        "expression": expressao,
                        "priority": prioridade,
                        "dependencies": deps,
                    },
                )

                ids[(host, nome)] = criada["triggerids"][0]

            configuradas += 1

        except Exception as erro:
            falhas += 1
            print(f"ERRO na trigger '{nome}' ({host}): {erro}")

    print(
        f"Triggers configuradas: {configuradas}/{len(TRIGGERS)}"
    )

    if falhas:
        sys.exit(f"{falhas} trigger(s) apresentaram erro.")


# ---------------------------------------------------------------------
# CADASTRO E ATUALIZACAO DOS HOSTS
# ---------------------------------------------------------------------

def cadastrar_hosts(gid):
    nomes = sorted(
        {
            template
            for host in HOSTS
            for template in host["templates"]
        }
    )

    achados = api(
        "template.get",
        {
            "output": ["templateid", "host"],
            "filter": {"host": nomes},
        },
    )

    ids_templates = {
        template["host"]: template["templateid"]
        for template in achados
    }

    faltando = [
        nome for nome in nomes
        if nome not in ids_templates
    ]

    if faltando:
        print("Templates NAO encontrados:", faltando)

        parecidos = api(
            "template.get",
            {
                "output": ["host"],
                "searchByAny": True,
                "search": {
                    "host": [
                        "Linux",
                        "Nginx",
                        "PostgreSQL",
                        "Network",
                        "SNMP",
                        "ICMP",
                    ]
                },
            },
        )

        print("Templates parecidos disponiveis:")

        for template in sorted(
            item["host"] for item in parecidos
        ):
            print("  -", template)

        sys.exit(1)

    for host in HOSTS:
        nome = host["host"]

        interface = {
            "type": 1,
            "main": 1,
            "useip": 1,
            "ip": host["ip"],
            "dns": "",
            "port": "10050",
        }

        if host.get("snmp"):
            interface = {
                "type": 2,
                "main": 1,
                "useip": 1,
                "ip": host["ip"],
                "dns": "",
                "port": "161",
                "details": {
                    "version": 2,
                    "bulk": 1,
                    "community": "{$SNMP_COMMUNITY}",
                },
            }

        macros = [
            {"macro": chave, "value": valor}
            for chave, valor in host["macros"].items()
        ]

        templates = [
            {"templateid": ids_templates[nome_template]}
            for nome_template in host["templates"]
        ]

        existente = api(
            "host.get",
            {
                "output": ["hostid"],
                "filter": {"host": [nome]},
                "selectInterfaces": ["interfaceid"],
            },
        )

        if existente:
            interfaces = existente[0]["interfaces"]

            if interfaces:
                interface["interfaceid"] = interfaces[0]["interfaceid"]

            api(
                "host.update",
                {
                    "hostid": existente[0]["hostid"],
                    "groups": [{"groupid": gid}],
                    "templates": templates,
                    "macros": macros,
                    "interfaces": [interface],
                },
            )

            print("Host atualizado:", nome)

        else:
            api(
                "host.create",
                {
                    "host": nome,
                    "interfaces": [interface],
                    "groups": [{"groupid": gid}],
                    "templates": templates,
                    "macros": macros,
                },
            )

            print("Host criado:", nome)


# ---------------------------------------------------------------------
# GRAFICO ICMP
# ---------------------------------------------------------------------

def grafico(host, nome, itens):
    resultado = api(
        "host.get",
        {
            "output": ["hostid"],
            "filter": {"host": [host]},
        },
    )

    if not resultado:
        print("Aviso: host nao encontrado para o grafico:", host)
        return

    hid = resultado[0]["hostid"]

    todos = api(
        "item.get",
        {
            "hostids": hid,
            "output": ["itemid", "key_"],
        },
    )

    itens_grafico = []

    for chave, cor, lado in itens:
        encontrados = [
            item for item in todos
            if item["key_"] == chave
            or item["key_"].startswith(chave + "[")
        ]

        if not encontrados:
            print("Aviso: item", chave, "nao encontrado em", host)
            return

        itens_grafico.append(
            {
                "itemid": encontrados[0]["itemid"],
                "color": cor,
                "yaxisside": lado,
            }
        )

    existente = api(
        "graph.get",
        {
            "hostids": hid,
            "filter": {"name": nome},
            "output": ["graphid"],
        },
    )

    if existente:
        api(
            "graph.update",
            {
                "graphid": existente[0]["graphid"],
                "gitems": itens_grafico,
            },
        )

        print("Grafico atualizado:", nome)

    else:
        api(
            "graph.create",
            {
                "name": nome,
                "width": 900,
                "height": 200,
                "gitems": itens_grafico,
            },
        )

        print("Grafico criado:", nome)


# ---------------------------------------------------------------------
# CONFIGURACAO PRINCIPAL
# ---------------------------------------------------------------------

def configurar():
    esperar_login()
    print("Login na API OK")

    grupos = api(
        "hostgroup.get",
        {"filter": {"name": [GRUPO]}},
    )

    if grupos:
        gid = grupos[0]["groupid"]
    else:
        gid = api(
            "hostgroup.create",
            {"name": GRUPO},
        )["groupids"][0]

    print("Grupo:", GRUPO)

    cadastrar_hosts(gid)

    grafico(
        "r-filial",
        "Enlace WAN: latencia (s) e perda (%) por ICMP",
        [
            ("icmppingsec", "1A7C11", 0),
            ("icmppingloss", "F63100", 1),
        ],
    )

    itens_de_servico()
    cenario_web()
    triggers()

    servidores = api(
        "host.get",
        {
            "output": ["hostid", "status"],
            "filter": {"host": ["Zabbix server"]},
        },
    )

    for servidor in servidores:
        if servidor["status"] == "0":
            api(
                "host.update",
                {
                    "hostid": servidor["hostid"],
                    "status": 1,
                },
            )
            print("Host padrao 'Zabbix server' desativado")

    for host in HOSTS:
        if not host.get("snmp"):
            continue

        resultado = api(
            "host.get",
            {
                "output": ["hostid"],
                "filter": {"host": [host["host"]]},
            },
        )

        regras = api(
            "discoveryrule.get",
            {
                "output": ["itemid"],
                "hostids": resultado[0]["hostid"],
            },
        )

        if not regras:
            continue

        try:
            api(
                "task.create",
                [
                    {
                        "type": 6,
                        "request": {"itemid": regra["itemid"]},
                    }
                    for regra in regras
                ],
            )

            print(
                f"Descoberta de interfaces disparada: "
                f"{host['host']} ({len(regras)} regras)"
            )

        except RuntimeError as erro:
            print("Aviso: descoberta nao iniciada:", erro)

    print("Configuracao concluida.")
    print("Aguarde cerca de 1 minuto e execute: make zabbix-status")


# ---------------------------------------------------------------------
# DIAGNOSTICO
# ---------------------------------------------------------------------

def status():
    esperar_login()

    nomes = {
        "0": "desconhecida",
        "1": "DISPONIVEL",
        "2": "INDISPONIVEL",
    }

    for host in HOSTS:
        resultado = api(
            "host.get",
            {
                "output": ["hostid"],
                "filter": {"host": [host["host"]]},
                "selectInterfaces": "extend",
            },
        )

        if not resultado:
            print(f"{host['host']}: nao cadastrado")
            continue

        hid = resultado[0]["hostid"]
        interfaces = resultado[0]["interfaces"]

        disponibilidade = "desconhecida"

        if interfaces:
            disponibilidade = nomes.get(
                interfaces[0].get("available"),
                "?",
            )

        total = api(
            "item.get",
            {
                "hostids": hid,
                "countOutput": True,
            },
        )

        ruins = api(
            "item.get",
            {
                "hostids": hid,
                "filter": {"state": "1"},
                "countOutput": True,
            },
        )

        print(
            f"{host['host']:14} interface: {disponibilidade:13} "
            f"itens: {int(total):3} nao suportados: {int(ruins)}"
        )

        if int(ruins) > 0:
            itens = api(
                "item.get",
                {
                    "hostids": hid,
                    "filter": {"state": "1"},
                    "output": ["name", "error"],
                    "limit": 50,
                },
            )

            for item in itens:
                if (
                    "installed packages" in item["name"]
                    or "waiting time" in item["name"]
                ):
                    continue

                print(
                    f"       - {item['name']}: "
                    f"{item['error'][:90]}"
                )


def status_icmp():
    print("--- ICMP (ping, perda e latencia) ---")

    for host in HOSTS:
        if (
            ICMP not in host["templates"]
            and NETDEV not in host["templates"]
        ):
            continue

        resultado = api(
            "host.get",
            {
                "output": ["hostid"],
                "filter": {"host": [host["host"]]},
            },
        )

        if not resultado:
            continue

        itens = api(
            "item.get",
            {
                "hostids": resultado[0]["hostid"],
                "search": {"key_": "icmpping"},
                "output": ["key_", "lastvalue"],
            },
        )

        valores = {
            item["key_"].split("[")[0]: item["lastvalue"]
            for item in itens
        }

        def numero(chave):
            try:
                return float(valores.get(chave, ""))
            except (ValueError, TypeError):
                return None

        ping = numero("icmpping")
        perda = numero("icmppingloss")
        segundos = numero("icmppingsec")

        if ping is None:
            resultado_ping = "sem dado"
        else:
            resultado_ping = "ok" if ping == 1 else "FALHOU"

        latencia = (
            "sem dado"
            if segundos is None
            else f"{segundos * 1000:.2f} ms"
        )

        percentual = "?" if perda is None else f"{perda:.0f}"

        print(
            f"{host['host']:14} {host['ip']:14} "
            f"ping={resultado_ping:8} "
            f"perda={percentual}% latencia={latencia}"
        )


def status_problemas():
    print("--- Problemas ativos (dependentes ocultos) ---")

    problemas = api(
        "trigger.get",
        {
            "output": ["description", "priority"],
            "filter": {"value": 1},
            "monitored": True,
            "skipDependent": True,
            "selectHosts": ["host"],
            "sortfield": "priority",
            "sortorder": "DESC",
        },
    )

    if not problemas:
        print("nenhum")
        return

    for trigger in problemas:
        host = (
            trigger["hosts"][0]["host"]
            if trigger.get("hosts")
            else "host desconhecido"
        )

        print(
            f"[sev {trigger['priority']}] "
            f"{host}: {trigger['description']}"
        )


# ---------------------------------------------------------------------
# EXECUCAO
# ---------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        esperar_login()
        status()
        status_icmp()
        status_problemas()
    else:
        configurar()
