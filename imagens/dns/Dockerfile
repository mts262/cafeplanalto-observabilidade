FROM coredns/coredns:1.12.1 AS coredns

FROM alpine:3.20
RUN apk add --no-cache iproute2 bind-tools
COPY --from=coredns /coredns /usr/local/bin/coredns
CMD ["coredns", "-conf", "/etc/coredns/Corefile"]
