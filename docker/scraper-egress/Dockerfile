FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends tinyproxy-bin adduser \
 && (id tinyproxy >/dev/null 2>&1 || adduser --system --group --no-create-home tinyproxy) \
 && rm -rf /var/lib/apt/lists/*
COPY tinyproxy.conf filter /etc/tinyproxy/
USER tinyproxy
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
