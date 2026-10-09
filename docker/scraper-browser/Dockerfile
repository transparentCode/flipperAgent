# Headless engine (Moli v1.1.15, linux aarch64) for the CoinGlass lane. No credentials, no mounts, non-root.
# The archive is downloaded on the host by scripts/fetch_moli.sh (the builder cannot reach GitHub releases)
# and verified again here.
FROM debian:bookworm-slim
ARG MOLI_SHA256=ddee0fc53b2d75bfabf59a1bf755d63c2d7fafce31435ca6a3958fbbb4a2d047
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libfontconfig1 \
 && rm -rf /var/lib/apt/lists/*
COPY vendor/moli-aarch64-unknown-linux-gnu.tar.gz /tmp/moli.tgz
RUN echo "${MOLI_SHA256}  /tmp/moli.tgz" | sha256sum -c - \
 && mkdir -p /opt/moli && tar -xzf /tmp/moli.tgz -C /opt/moli && rm -f /tmp/moli.tgz \
 && useradd --system --no-create-home --uid 10001 moli
USER 10001
ENV HOME=/tmp PATH=/opt/moli/moli-v1.1.15-aarch64-unknown-linux-gnu:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EXPOSE 9222
CMD ["moli", "serve", "--host", "0.0.0.0", "--port", "9222"]
