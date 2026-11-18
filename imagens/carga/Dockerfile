FROM grafana/k6:latest AS k6

FROM alpine:3.20
RUN apk add --no-cache iproute2 curl bind-tools
COPY --from=k6 /usr/bin/k6 /usr/bin/k6
CMD ["sleep", "infinity"]
