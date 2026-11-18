import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open(wait=False)
    yield
    pool.close()


app = FastAPI(title="Loja Cafe Planalto", lifespan=lifespan)


@app.exception_handler(psycopg.Error)
async def erro_banco(request, exc):
    return JSONResponse(status_code=503, content={"erro": "banco indisponivel"})


class NovoPedido(BaseModel):
    produto_id: int
    quantidade: int = Field(gt=0)


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
        return conn.execute(
            "INSERT INTO pedidos (produto_id, quantidade, valor) "
            "VALUES (%s, %s, %s) RETURNING id, produto_id, quantidade, valor, criado_em",
            (pedido.produto_id, pedido.quantidade, valor),
        ).fetchone()


@app.get("/health")
def health():
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception:
        raise HTTPException(status_code=503, detail="banco indisponivel")
    return {"status": "ok"}
