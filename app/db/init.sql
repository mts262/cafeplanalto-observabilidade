CREATE TABLE produtos (
    id      SERIAL PRIMARY KEY,
    nome    TEXT NOT NULL,
    preco   NUMERIC(10,2) NOT NULL,
    estoque INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE pedidos (
    id         SERIAL PRIMARY KEY,
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    quantidade INTEGER NOT NULL CHECK (quantidade > 0),
    valor      NUMERIC(10,2) NOT NULL,
    criado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO produtos (nome, preco) VALUES
    ('Cafe Bourbon Amarelo 250g', 38.90),
    ('Cafe Catuai Vermelho 250g', 34.50),
    ('Cafe Geisha 250g',          89.00),
    ('Cafe Torra Escura 500g',    52.00),
    ('Cafe Descafeinado 250g',    41.00);
