import http from 'k6/http';
import { check } from 'k6';

export const options = {
  scenarios: {
    carga_loja: {
      executor: 'constant-arrival-rate',
      rate: 10,
      timeUnit: '1s',
      duration: '12h',
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
  },
};

const BASE = 'http://loja.cafeplanalto.lab';
const CABECALHO = { 'Content-Type': 'application/json' };

export default function () {
  if (Math.random() < 0.8) {
    const r = http.get(`${BASE}/produtos`, { timeout: '5s' });
    check(r, { 'catalogo 200': (resp) => resp.status === 200 });
  } else {
    const corpo = JSON.stringify({
      produto_id: 1 + Math.floor(Math.random() * 5),
      quantidade: 1 + Math.floor(Math.random() * 3),
    });
    const r = http.post(`${BASE}/pedidos`, corpo, { headers: CABECALHO, timeout: '5s' });
    check(r, { 'pedido 201': (resp) => resp.status === 201 });
  }
}
