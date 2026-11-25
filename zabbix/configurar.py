#!/usr/bin/env python3
"""Configura o Zabbix pela API: grupo, hosts e templates (idempotente).

Uso:
  python3 zabbix/configurar.py          cadastra grupo e hosts
  python3 zabbix/configurar.py status   mostra disponibilidade e itens dos hosts
"""
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
    {"host": "dns", "ip": "172.20.10.10", "templates": [LINUX], "macros": {}},
    {"host": "web", "ip": "172.20.10.20",
     "templates": [LINUX, "Nginx by Zabbix agent"], "macros": NGINX},
    {"host": "api", "ip": "172.20.10.21", "templates": [LINUX], "macros": {}},
    {"host": "db", "ip": "172.20.10.22",
     "templates": [LINUX, "PostgreSQL by Zabbix agent 2"], "macros": PG},
    {"host": "r-matriz", "ip": "172.20.99.1", "snmp": True,
     "templates": [NETDEV], "macros": SNMPM},
    {"host": "r-filial", "ip": "10.0.0.2", "snmp": True,
     "templates": [NETDEV], "macros": SNMPM},
    {"host": "cliente-carga", "ip": "172.20.20.20",
     "templates": [ICMP], "macros": {}},
]

token = None


def api(metodo, params=None):
    corpo = {"jsonrpc": "2.0", "method": metodo,
             "params": params if params is not None else {}, "id": 1}
    cab = {"Content-Type": "application/json-rpc"}
    if token:
        cab["Authorization"] = "Bearer " + token
    req = urllib.request.Request(URL, json.dumps(corpo).encode(), cab)
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.load(r)
    if "error" in resp:
        e = resp["error"]
        raise RuntimeError(f"{metodo}: {e.get('message')} {e.get('data')}")
    return resp["result"]


def esperar_login():
    global token
    ultimo = ""
    limite = time.time() + 300
    while time.time() < limite:
        try:
            token = None
            token = api("user.login", {"username": USUARIO, "password": SENHA})
            return
        except Exception as e:
            ultimo = str(e)
            time.sleep(5)
    sys.exit(f"Zabbix nao ficou pronto em 5 minutos: {ultimo}")


# ---------------------------------------------------------------- Z5 e Z6
LOJA = "Loja"
LOJA_URL = "http://loja.cafeplanalto.lab"

# (host, nome, chave, descricao do trigger de servico parado)
SERVICOS = [
    ("web", "Porta 80 (Nginx)", "net.tcp.service[tcp,127.0.0.1,80]", "Nginx"),
    ("api", "Porta 8000 (API)", "net.tcp.service[tcp,127.0.0.1,8000]", "API"),
    ("db", "Porta 5432 (PostgreSQL)", "net.tcp.service[tcp,127.0.0.1,5432]", "PostgreSQL"),
    ("dns", "Porta 53 (CoreDNS)", "net.tcp.service[tcp,127.0.0.1,53]", "CoreDNS"),
]

# Severidades: 2 aviso, 3 media, 4 alta, 5 desastre
T_MATRIZ = "Roteador r-matriz inacessivel (ICMP)"
T_WAN = "Enlace WAN fora: r-filial inacessivel (ICMP)"
T_WAN_RUIM = "Enlace WAN degradado (latencia > 150 ms ou perda > 2%)"
T_HOST = "Host indisponivel (agente sem resposta)"
T_LOJA = "Loja fora do ar (cenario web falhou)"
T_CARGA = "Host cliente-carga inacessivel (ICMP)"
CPU = "CPU alta (media > 80% em 5 min)"

# (host, nome, expressao, severidade, [(host, nome) dos quais depende])
# A ordem importa: a dependencia precisa existir antes de quem depende dela.
TRIGGERS = [
    ("r-matriz", T_MATRIZ, "max(/r-matriz/icmpping,#3)=0", 4, []),
    ("r-filial", T_WAN, "max(/r-filial/icmpping,#3)=0", 5,
     [("r-matriz", T_MATRIZ)]),
    ("r-filial", T_WAN_RUIM,
     "avg(/r-filial/icmppingsec,#3)>0.15 or avg(/r-filial/icmppingloss,#3)>2", 3,
     [("r-filial", T_WAN)]),
    ("cliente-carga", T_CARGA, "max(/cliente-carga/icmpping,#3)=0", 4,
     [("r-filial", T_WAN)]),
] + [
    (h, T_HOST, f"nodata(/{h}/agent.ping,3m)=1", 4, [("r-matriz", T_MATRIZ)])
    for h in ("dns", "web", "api", "db")
] + [
    (h, f"Servico parado: {nome}", f"max(/{h}/{chave},#2)=0", 4, [(h, T_HOST)])
    for h, _, chave, nome in SERVICOS
] + [
    (h, CPU, f"avg(/{h}/system.cpu.util,5m)>80", 2, [(h, T_HOST)])
    for h in ("dns", "web", "api", "db")
] + [
    ("web", T_LOJA, f"last(/web/web.test.fail[{LOJA}])<>0", 5,
     [("r-matriz", T_MATRIZ)]),
]


def id_host(nome):
    r = api("host.get", {"output": ["hostid"], "filter": {"host": [nome]}})
    if not r:
        sys.exit(f"Host {nome} nao cadastrado")
    return r[0]["hostid"]


def itens_de_servico():
    """Itens do agente que checam se a porta de cada servico responde."""
    for host, nome, chave, _ in SERVICOS:
        hid = id_host(host)
        if api("item.get", {"hostids": hid, "filter": {"key_": chave}}):
            continue
        ifaces = api("hostinterface.get", {"hostids": hid, "filter": {"type": 1}})
        api("item.create", {"name": f"Servico: {nome}", "key_": chave,
                            "hostid": hid, "type": 0, "value_type": 3,
                            "delay": "30s", "interfaceid": ifaces[0]["interfaceid"]})
        print("Item criado:", host, chave)


def cenario_web():
    """Z5: cenario com 2 passos (catalogo e pedido), rodando a partir do servidor."""
    hid = id_host("web")
    if api("httptest.get", {"hostids": hid, "filter": {"name": LOJA}}):
        return
    api("httptest.create", {
        "name": LOJA, "hostid": hid, "delay": "30s", "retries": 1,
        "steps": [
            {"name": "Abrir catalogo", "no": 1, "url": f"{LOJA_URL}/produtos",
             "status_codes": "200", "required": "Cafe", "timeout": "10s"},
            {"name": "Criar pedido", "no": 2, "url": f"{LOJA_URL}/pedidos",
             "posts": '{"produto_id": 1, "quantidade": 1}',
             "headers": [{"name": "Content-Type", "value": "application/json"}],
             "status_codes": "201", "required": "produto_id", "timeout": "10s"},
        ]})
    print("Cenario web criado:", LOJA)


def triggers():
    """Z6: triggers com severidade e dependencias (evita alertas em cascata)."""
    ids = {}

    def achar(host, nome):
        if (host, nome) not in ids:
            r = api("trigger.get", {"hostids": id_host(host), "output": ["triggerid"],
                                    "filter": {"description": nome}})
            if not r:
                sys.exit(f"Trigger '{nome}' de {host} nao existe (dependencia)")
            ids[(host, nome)] = r[0]["triggerid"]
        return ids[(host, nome)]

    for host, nome, expr, prio, deps in TRIGGERS:
        dep = [{"triggerid": achar(*d)} for d in deps]
        r = api("trigger.get", {"hostids": id_host(host), "output": ["triggerid"],
                                "filter": {"description": nome}})
        try:
            if r:
                api("trigger.update", {"triggerid": r[0]["triggerid"],
                                       "expression": expr, "priority": prio,
                                       "dependencies": dep})
                ids[(host, nome)] = r[0]["triggerid"]
            else:
                criado = api("trigger.create", {"description": nome,
                                                "expression": expr, "priority": prio,
                                                "dependencies": dep})
                ids[(host, nome)] = criado["triggerids"][0]
        except RuntimeError as e:
            print(f"ERRO no trigger '{nome}' ({host}): {e}")
            continue
    print(f"Triggers configurados: {len(TRIGGERS)}")


def configurar():
    esperar_login()
    print("Login na API OK")

    g = api("hostgroup.get", {"filter": {"name": [GRUPO]}})
    if g:
        gid = g[0]["groupid"]
    else:
        gid = api("hostgroup.create", {"name": GRUPO})["groupids"][0]
    print("Grupo:", GRUPO)

    nomes = sorted({t for h in HOSTS for t in h["templates"]})
    achados = api("template.get", {"output": ["templateid", "host"],
                                   "filter": {"host": nomes}})
    ids = {t["host"]: t["templateid"] for t in achados}
    faltando = [n for n in nomes if n not in ids]
    if faltando:
        parecidos = api("template.get", {
            "output": ["host"], "searchByAny": True,
            "search": {"host": ["Linux", "Nginx", "PostgreSQL", "Network", "SNMP", "ICMP"]}})
        print("Templates NAO encontrados:", faltando)
        print("Templates parecidos disponiveis:")
        for nome in sorted(t["host"] for t in parecidos):
            print("  -", nome)
        sys.exit(1)

    def cadastrar(h):
        interface = {"type": 1, "main": 1, "useip": 1,
                     "ip": h["ip"], "dns": "", "port": "10050"}
        if h.get("snmp"):
            interface = {"type": 2, "main": 1, "useip": 1, "ip": h["ip"],
                         "dns": "", "port": "161",
                         "details": {"version": 2, "bulk": 1,
                                     "community": "{$SNMP_COMMUNITY}"}}
        macros = [{"macro": k, "value": v} for k, v in h["macros"].items()]
        templates = [{"templateid": ids[t]} for t in h["templates"]]
        existente = api("host.get", {"output": ["hostid"],
                                     "filter": {"host": [h["host"]]},
                                     "selectInterfaces": ["interfaceid"]})
        if existente:
            iid = existente[0]["interfaces"][0]["interfaceid"]
            api("host.update", {
                "hostid": existente[0]["hostid"],
                "groups": [{"groupid": gid}],
                "templates": templates, "macros": macros,
                "interfaces": [dict(interface, interfaceid=iid)]})
            print("Host atualizado:", h["host"])
        else:
            api("host.create", {
                "host": h["host"], "interfaces": [interface],
                "groups": [{"groupid": gid}],
                "templates": templates, "macros": macros})
            print("Host criado:", h["host"])

    for h in HOSTS:
        for tentativa in range(1, 4):
            try:
                cadastrar(h)
                break
            except OSError as e:
                print(f"{h['host']}: demorou demais ({e}), tentativa {tentativa}/3")
                time.sleep(10)
        else:
            sys.exit(f"Falha ao cadastrar {h['host']}")

    def grafico(host, nome, itens):
        r = api("host.get", {"output": ["hostid"], "filter": {"host": [host]}})
        hid = r[0]["hostid"]
        if api("graph.get", {"hostids": hid, "filter": {"name": nome}}):
            return
        todos = api("item.get", {"hostids": hid, "search": {"key_": "icmpping"},
                                 "output": ["itemid", "key_"]})
        gitems = []
        for chave, cor, lado in itens:
            achado = [i for i in todos
                      if i["key_"] == chave or i["key_"].startswith(chave + "[")]
            if not achado:
                print("Aviso: item", chave, "nao encontrado em", host)
                return
            gitems.append({"itemid": achado[0]["itemid"], "color": cor,
                           "yaxisside": lado})
        api("graph.create", {"name": nome, "width": 900, "height": 200,
                             "gitems": gitems})
        print("Grafico criado:", nome)

    grafico("r-filial", "Enlace WAN: latencia (s) e perda (%) por ICMP",
            [("icmppingsec", "1A7C11", 0), ("icmppingloss", "F63100", 1)])

    itens_de_servico()
    cenario_web()
    triggers()

    for s in api("host.get", {"output": ["hostid", "status"],
                              "filter": {"host": ["Zabbix server"]}}):
        if s["status"] == "0":
            api("host.update", {"hostid": s["hostid"], "status": 1})
            print("Host padrao 'Zabbix server' desativado")

    for h in HOSTS:
        if not h.get("snmp"):
            continue
        r = api("host.get", {"output": ["hostid"], "filter": {"host": [h["host"]]}})
        regras = api("discoveryrule.get", {"output": ["itemid"], "hostids": r[0]["hostid"]})
        try:
            api("task.create", [{"type": 6, "request": {"itemid": x["itemid"]}} for x in regras])
            print(f"Descoberta de interfaces disparada: {h['host']} ({len(regras)} regras)")
        except RuntimeError as e:
            print("Aviso: nao consegui forcar a descoberta:", e)

    print("Pronto. Aguarde cerca de 1 minuto e rode: make zabbix-status")


def status():
    esperar_login()
    nomes = {"0": "desconhecida", "1": "DISPONIVEL", "2": "INDISPONIVEL"}
    for h in HOSTS:
        r = api("host.get", {"output": ["hostid"],
                             "filter": {"host": [h["host"]]},
                             "selectInterfaces": "extend"})
        if not r:
            print(f"{h['host']}: nao cadastrado")
            continue
        hid = r[0]["hostid"]
        disp = nomes.get(r[0]["interfaces"][0].get("available"), "?")
        total = api("item.get", {"hostids": hid, "countOutput": True})
        ruins = api("item.get", {"hostids": hid, "filter": {"state": "1"},
                                 "countOutput": True})
        print(f"{h['host']:4} interface: {disp:13} itens: {total:>3}  "
              f"nao suportados: {ruins}")
        if ruins != "0":
            for i in api("item.get", {"hostids": hid,
                                      "filter": {"state": "1"},
                                      "output": ["name", "error"],
                                      "limit": 50}):
                if "installed packages" in i["name"] or "waiting time" in i["name"]:
                    continue
                print(f"       - {i['name']}: {i['error'][:90]}")


def status_icmp():
    print("--- ICMP (ping, perda e latencia) ---")
    for h in HOSTS:
        if ICMP not in h["templates"] and NETDEV not in h["templates"]:
            continue
        r = api("host.get", {"output": ["hostid"], "filter": {"host": [h["host"]]}})
        if not r:
            continue
        itens = api("item.get", {"hostids": r[0]["hostid"],
                                 "search": {"key_": "icmpping"},
                                 "output": ["key_", "lastvalue"]})
        v = {i["key_"].split("[")[0]: i["lastvalue"] for i in itens}

        def num(k):
            try:
                return float(v.get(k, ""))
            except ValueError:
                return None

        ping, perda, seg = num("icmpping"), num("icmppingloss"), num("icmppingsec")
        if ping is None:
            res = "sem dado"
        else:
            res = "ok" if ping == 1 else "FALHOU"
        lat = "sem dado" if seg is None else f"{seg * 1000:.2f} ms"
        pct = "?" if perda is None else f"{perda:.0f}"
        print(f"{h['host']:14} {h['ip']:14} ping={res:8} perda={pct}%  latencia={lat}")


def status_problemas():
    print("--- Problemas ativos (dependentes ocultos) ---")
    ps = api("trigger.get", {"output": ["description", "priority"],
                             "filter": {"value": 1}, "monitored": True,
                             "skipDependent": True, "selectHosts": ["host"],
                             "sortfield": "priority", "sortorder": "DESC"})
    if not ps:
        print("nenhum")
    for t in ps:
        print(f"[sev {t['priority']}] {t['hosts'][0]['host']}: {t['description']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        status()
        status_icmp()
        status_problemas()
    else:
        configurar()
