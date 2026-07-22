# MCP proxy container for flipperAgent
# Exposes codebase-memory-mcp and gitnexus as standard MCP HTTP/SSE servers
# via mcp-proxy named servers.

# ---------------------------------------------------------------------------
# Stage 1: Pre-built GitNexus source
# ---------------------------------------------------------------------------
FROM ghcr.io/abhigyanpatwari/gitnexus:1.6.9 AS gitnexus-src

# ---------------------------------------------------------------------------
# Stage 2: codebase-memory-mcp static binary
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
# Stage 3: Runtime image
# ---------------------------------------------------------------------------
FROM ubuntu:24.04
ARG NODE_VERSION=22.22.2
ARG MCP_PROXY_VERSION=0.12.0

# Install Python (mcp-proxy), Node.js (gitnexus), curl (healthcheck), and git.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git python3 python3-pip \
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

# Install mcp-proxy.
RUN pip3 install --break-system-packages mcp-proxy==${MCP_PROXY_VERSION}

# Patch mcp-proxy so tools/list pagination (cursor) is forwarded to the stdio
# backend. Without this, only the first page of tools is ever returned.
RUN python3 - <<'PY'
import pathlib
path = pathlib.Path("/usr/local/lib/python3.12/dist-packages/mcp_proxy/proxy_server.py")
source = path.read_text()
old = '''        async def _list_tools(_: t.Any) -> types.ServerResult:  # noqa: ANN401
            tools = await remote_app.list_tools()
            return types.ServerResult(tools)'''
new = '''        async def _list_tools(req: types.ListToolsRequest) -> types.ServerResult:
            cursor = req.params.cursor if req.params else None
            tools = await remote_app.list_tools(cursor)
            return types.ServerResult(tools)'''
if old not in source:
    raise RuntimeError("proxy_server.py patch target not found; mcp-proxy may have changed")
path.write_text(source.replace(old, new))
PY

# Copy cbm binary.
COPY --from=cbm-bin /usr/local/bin/codebase-memory-mcp /usr/local/bin/codebase-memory-mcp

# Copy GitNexus from the upstream pre-built image.
COPY --from=gitnexus-src /app/gitnexus /app/gitnexus
# The upstream image uses a symlink to /app/gitnexus/dist/cli/index.js. Running
# that symlink from /workspace breaks Node module resolution, so install a
# wrapper that executes gitnexus from its own directory.
RUN rm -f /usr/local/bin/gitnexus && \
    printf '%s\n' '#!/bin/bash' 'cd /app/gitnexus || exit 1' 'exec node dist/cli/index.js "$@"' > /usr/local/bin/gitnexus && \
    chmod +x /usr/local/bin/gitnexus

# Create non-root user and writable cache directories.
RUN groupadd -r mcp && useradd -r -g mcp mcp && \
    mkdir -p /data/cbm /data/gitnexus /workspace && \
    chown -R mcp:mcp /data /workspace

WORKDIR /workspace
USER mcp

ENV CBM_CACHE_DIR=/data/cbm
ENV HOME=/data/gitnexus
ENV PATH="/usr/local/bin:/app/gitnexus/node_modules/.bin:${PATH}"

# mcp-proxy exposes one port for all named servers.
EXPOSE 9748

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:9748/status > /dev/null || exit 1

ENTRYPOINT ["mcp-proxy"]
CMD ["--host", "0.0.0.0", "--port", "9748", "--pass-environment", "--named-server", "cbm", "codebase-memory-mcp", "--named-server", "gitnexus", "gitnexus mcp"]
