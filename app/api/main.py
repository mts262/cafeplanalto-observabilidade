import asyncio
import json
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest,
)
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

DSN = (
    f"host={os.getenv('DB_HOST', 'db.cafeplanalto.lab')} "
    f"port={os.getenv('DB_PORT', '5432')} "
    f"dbname={os.getenv('DB_NAME', 'loja')} "
    f"user={os.getenv('DB_USER', 'loja')} "
    f"password={os.getenv('DB_PASSWORD', 'loja123')} "
    "connect_timeout=3"
)

# open=False: o pool abre no startup sem travar se o banco ainda nao subiu
pool = ConnectionPool(
    DSN, min_size=1, max_size=10, open=False, timeout=3,
    kwargs={"row_factory": dict_row},
)

# ---------- Metricas (Prometheus) ----------
REQUISICOES = Counter(
    "http_requests_total", "Total de requisicoes HTTP", ["rota", "metodo", "status"]
)
DURACAO = Histogram(
    "http_request_duration_seconds", "Duracao das requisicoes HTTP", ["rota"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1, 2, 5),
)
PEDIDOS = Counter("pedidos_criados_total", "Pedidos criados")
FATURAMENTO = Counter("pedidos_valor_reais_total", "Valor total dos pedidos em reais")
POOL_EM_USO = Gauge("db_pool_conexoes_em_uso", "Conexoes do pool em uso")


def _pool_em_uso():
    stats = pool.get_stats()
    return stats.get("pool_size", 0) - stats.get("pool_available", 0)


POOL_EM_USO.set_function(_pool_em_uso)

# ---------- Caos (falhas injetadas) ----------
caos = {"latencia_ms": 0, "taxa_erro": 0.0}
ROTAS_CONHECIDAS = {"/", "/produtos", "/pedidos", "/health", "/metrics", "/admin/caos"}
ROTAS_SEM_CAOS = {"/health", "/metrics", "/admin/caos"}


def log_json(**campos):
    registro = {"timestamp": datetime.now(timezone.utc).isoformat(), **campos}
    print(json.dumps(registro, ensure_ascii=False), flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open(wait=False)
    yield
    pool.close()


app = FastAPI(title="Loja Cafe Planalto", lifespan=lifespan)


@app.middleware("http")
async def observabilidade(request: Request, call_next):
    inicio = time.perf_counter()
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
    caminho = request.url.path
    try:
        if caminho not in ROTAS_SEM_CAOS and caos["latencia_ms"] > 0:
            await asyncio.sleep(caos["latencia_ms"] / 1000)
        if (
            caminho not in ROTAS_SEM_CAOS
            and caos["taxa_erro"] > 0
            and random.random() < caos["taxa_erro"]
        ):
            resposta = JSONResponse(status_code=500, content={"erro": "falha injetada"})
        else:
            resposta = await call_next(request)
    except Exception as exc:
        log_json(nivel="ERROR", rota=caminho, status=500, trace_id=trace_id,
                 mensagem="erro nao tratado", detalhe=type(exc).__name__)
        resposta = JSONResponse(status_code=500, content={"erro": "erro interno"})

    duracao = time.perf_counter() - inicio
    rota = caminho if caminho in ROTAS_CONHECIDAS else "desconhecida"
    status = resposta.status_code

    REQUISICOES.labels(rota, request.method, str(status)).inc()
    DURACAO.labels(rota).observe(duracao)

    if caminho != "/metrics":
        nivel = "ERROR" if status >= 500 else "WARNING" if status >= 400 else "INFO"
        log_json(nivel=nivel, rota=rota, status=status,
                 duracao_ms=round(duracao * 1000, 1), trace_id=trace_id,
                 metodo=request.method)
    resposta.headers["X-Trace-Id"] = trace_id
    return resposta


@app.exception_handler(psycopg.Error)
async def erro_banco(request, exc):
    log_json(nivel="ERROR", rota=request.url.path, status=503,
             mensagem="erro de conexao com o banco", detalhe=type(exc).__name__)
    return JSONResponse(status_code=503, content={"erro": "banco indisponivel"})


class NovoPedido(BaseModel):
    produto_id: int
    quantidade: int = Field(gt=0)


class Caos(BaseModel):
    latencia_ms: Optional[int] = Field(default=None, ge=0, le=10000)
    taxa_erro: Optional[float] = Field(default=None, ge=0, le=1)


@app.get("/produtos")
def listar_produtos():
    with pool.connection() as conn:
        return conn.execute(
            "SELECT id, nome, preco FROM produtos ORDER BY id"
        ).fetchall()


@app.post("/pedidos", status_code=201)
def criar_pedido(pedido: NovoPedido):
    with pool.connection() as conn:
        produto = conn.execute(
            "SELECT preco FROM produtos WHERE id = %s", (pedido.produto_id,)
        ).fetchone()
        if produto is None:
            raise HTTPException(status_code=404, detail="produto nao encontrado")
        valor = produto["preco"] * pedido.quantidade
        criado = conn.execute(
            "INSERT INTO pedidos (produto_id, quantidade, valor) "
            "VALUES (%s, %s, %s) RETURNING id, produto_id, quantidade, valor, criado_em",
            (pedido.produto_id, pedido.quantidade, valor),
        ).fetchone()
    PEDIDOS.inc()
    FATURAMENTO.inc(float(valor))
    return criado


@app.get("/health")
def health():
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception:
        raise HTTPException(status_code=503, detail="banco indisponivel")
    return {"status": "ok"}


@app.get("/metrics")
def metricas():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/admin/caos")
def ver_caos():
    return caos


@app.post("/admin/caos")
def definir_caos(c: Caos):
    if c.latencia_ms is not None:
        caos["latencia_ms"] = c.latencia_ms
    if c.taxa_erro is not None:
        caos["taxa_erro"] = c.taxa_erro
    log_json(nivel="WARNING", rota="/admin/caos", status=200,
             mensagem="caos alterado", caos=dict(caos))
    return caos
