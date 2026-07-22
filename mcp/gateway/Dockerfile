# MCP Gateway container for flipperAgent
# Bundles mcp-gateway, codebase-memory-mcp, and gitnexus in one image.
# Multi-stage build: copies pre-built GitNexus from its upstream image so we
# avoid compiling native Node modules in this layer.

# ---------------------------------------------------------------------------
# Stage 1: Pre-built GitNexus source
# GitNexus publishes a Debian-based image with gitnexus already installed.
# We copy /app/gitnexus into the runtime stage.
# ---------------------------------------------------------------------------
FROM ghcr.io/abhigyanpatwari/gitnexus:1.6.9 AS gitnexus-src

# ---------------------------------------------------------------------------
# Stage 2: mcp-gateway static binary
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS mcp-gateway-bin
ARG MCP_GATEWAY_VERSION=3.3.2
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
        amd64) MGW_ARCH="x86_64" ;; \
        arm64) MGW_ARCH="aarch64" ;; \
        *) echo "Unsupported architecture: $ARCH"; exit 1 ;; \
    esac \
    && curl -fsSL -o /mcp-gateway \
        "https://github.com/MikkoParkkola/mcp-gateway/releases/download/v${MCP_GATEWAY_VERSION}/mcp-gateway-linux-${MGW_ARCH}" \
    && chmod +x /mcp-gateway

# ---------------------------------------------------------------------------
# Stage 3: codebase-memory-mcp binary
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS cbm-bin
ARG CBM_VERSION=0.9.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tar \
    && rm -rf /var/lib/apt/lists/* \
    && ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
        amd64) CBM_ARCH="amd64" ;; \
        arm64) CBM_ARCH="arm64" ;; \
        *) echo "Unsupported architecture: $ARCH"; exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/cbm.tar.gz \
        "https://github.com/DeusData/codebase-memory-mcp/releases/download/v${CBM_VERSION}/codebase-memory-mcp-linux-${CBM_ARCH}.tar.gz" \
    && tar -xzf /tmp/cbm.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/codebase-memory-mcp \
    && rm -f /tmp/cbm.tar.gz

# ---------------------------------------------------------------------------
# Stage 4: runtime image
# ---------------------------------------------------------------------------
FROM ubuntu:24.04
ARG NODE_VERSION=22.22.2

# Install runtime dependencies: curl for healthcheck, git for GitNexus, ca-certificates for HTTPS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js from the official binary distribution.
RUN ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
        amd64) NODE_TARBALL_ARCH="x64" ;; \
        arm64) NODE_TARBALL_ARCH="arm64" ;; \
        *) echo "Unsupported architecture: $ARCH"; exit 1 ;; \
    esac \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_TARBALL_ARCH}.tar.gz" -o /tmp/node.tar.gz \
    && tar -xzf /tmp/node.tar.gz -C /usr/local --strip-components=1 \
    && rm -f /tmp/node.tar.gz \
    && node --version

# Copy GitNexus from the upstream pre-built image.
COPY --from=gitnexus-src /app/gitnexus /app/gitnexus
# The upstream image uses a symlink to /app/gitnexus/dist/cli/index.js. Running
# that symlink from /workspace breaks Node module resolution, so install a tiny
# wrapper that executes gitnexus from its own directory.
RUN rm -f /usr/local/bin/gitnexus && \
    printf '%s\n' '#!/bin/bash' 'cd /app/gitnexus || exit 1' 'exec node dist/cli/index.js "$@"' > /usr/local/bin/gitnexus && \
    chmod +x /usr/local/bin/gitnexus

# Copy mcp-gateway and codebase-memory-mcp binaries.
COPY --from=mcp-gateway-bin /mcp-gateway /usr/local/bin/mcp-gateway
COPY --from=cbm-bin /usr/local/bin/codebase-memory-mcp /usr/local/bin/codebase-memory-mcp

# Create non-root user and writable cache directories.
RUN groupadd -r mcp && useradd -r -g mcp mcp && \
    mkdir -p /data/cbm /data/gitnexus /workspace /config && \
    chown -R mcp:mcp /data /workspace /config

WORKDIR /workspace
USER mcp

ENV CBM_CACHE_DIR=/data/cbm
ENV HOME=/data/gitnexus
ENV PATH="/usr/local/bin:/app/gitnexus/node_modules/.bin:${PATH}"

# Runtime config is mounted at /config/gateway.yaml by docker-compose.
EXPOSE 9747

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:9747/health > /dev/null || exit 1

ENTRYPOINT ["mcp-gateway"]
CMD ["serve", "--config", "/config/gateway.yaml", "--log-level", "info"]
