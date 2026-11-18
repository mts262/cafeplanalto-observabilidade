#!/bin/sh
# Espera a loja responder (o IP e o DNS sao configurados depois do start do conteiner)
until wget -q -O /dev/null http://loja.cafeplanalto.lab/health; do sleep 2; done
# Roda o k6 em loop: se o cenario terminar, recomeca
while true; do
  k6 run --quiet /carga/loja.js
  sleep 1
done
