---
goal: 'Eliminate dangling MCP processes and provide resilient, containerized code-intelligence infrastructure for GitNexus and codebase-memory-mcp'
stage: 'coder-to-orchestrator'
date_created: '2026-07-22'
last_updated: '2026-07-22'
owner: 'Quant Orchestrator'
source_agent: 'Quant Coder'
target_agent: 'Quant Orchestrator'
status: 'Implemented'
tags: ['handoff', 'quant', 'infrastructure', 'docker', 'mcp', 'code-intelligence']
---

# MCP Fallback & Containerization Policy v1 — Implemented

## Objective
Provide a reliable, observable, and easy-to-recover deployment model for the two code-intelligence MCP servers used by `flipperAgent`:

1. `codebase-memory-mcp` (primary per `AGENTS.md`)
2. `gitnexus` (tactical fallback)

The immediate pain point was **dangling stdio child processes** left behind when the IDE, agent, or shell exits uncleanly. The implemented solution is a single `mcp-gateway` Docker container that spawns both stdio backends internally and exposes them on long-running **HTTP MCP** direct routes, falling back to local stdio only when the container is down.

## Final State

| Tool | Transport | Container Route | Index State |
|---|---|---|---|
| `codebase-memory-mcp` | HTTP via `mcp-gateway` stdio backend | `http://localhost:9747/mcp/cbm` | `flipperAgent-src` (22,465 nodes, 116,478 edges) + `flipperAgent-tests` (5,335 nodes, 22,350 edges) |
| `gitnexus` | HTTP via `mcp-gateway` stdio backend | `http://localhost:9747/mcp/gitnexus` | `flipperAgent` (46,991 nodes, 77,460 edges) |

`docker compose -f mcp-compose.yml down` kills the entire process tree and leaves no host orphans.

## Key Implementation Decisions

1. **Base image: `ubuntu:24.04`** — `codebase-memory-mcp` v0.9.0 needs glibc 2.38 / libstdc++ 3.4.32; Debian Bookworm (glibc 2.36) failed at runtime.
2. **Multi-stage Dockerfile** — copies the pre-built GitNexus image to avoid compiling native tree-sitter modules. Final image is **374 MB** (vs. 3.3 GB in the first single-stage attempt).
3. **GitNexus wrapper script** — replaces the upstream symlink with a wrapper that executes from `/app/gitnexus` so Node module resolution works from the gateway's `/workspace` working directory.
4. **Writable repo mount for GitNexus** — GitNexus stores its index at `<repo>/.gitnexus/`, so the repo is mounted read-write and `analyze` is invoked with `--index-only` to avoid touching `AGENTS.md`/`CLAUDE.md`.
5. **Split cbm projects** — `codebase-memory-mcp` can index the code directories in this repo, but `research/` contains large JSON/JSONL/CSV files that exceed the worker's per-process memory budget (~1 GB in this Docker setup). cbm has no directory-exclude option, so `src/`, `tests/`, `conductor/`, `scripts/`, `docs/`, and `plans/` are indexed as separate projects; `research/` is skipped for cbm and covered by GitNexus instead.
6. **Timeout tuning** — request and health-check timeouts were raised during initial indexing and then reduced to 120 s for normal operation.

## Quick Start

```bash
docker compose -f mcp-compose.yml up -d
./mcp/scripts/mcp-status.sh
./mcp/scripts/mcp-index.sh   # re-index after code changes
docker compose -f mcp-compose.yml down
```

## Fallback Policies

### Layer 1 — Primary: Containerized HTTP MCP
Use `mcp-compose.yml` and the HTTP endpoints in `.vscode/mcp.json`.

### Layer 2 — Fallback: Local Stdio
Rename `.vscode/mcp.json.stdio-fallback` to `.vscode/mcp.json` if Docker is unavailable.

### Layer 3 — Emergency: Direct CLI
Use local `codebase-memory-mcp` binary or `npx gitnexus` for one-off queries.

## Acceptance Criteria — Verified

- [x] Gateway starts and `/health` reports both backends healthy.
- [x] Both backends warm-start (cbm 8 tools, gitnexus 17 tools).
- [x] VS Code Copilot endpoints configured for HTTP.
- [x] `docker compose down` leaves no host MCP processes.
- [x] GitNexus indexes the whole repo.
- [x] codebase-memory-mcp indexes `src/`, `tests/`, `conductor/`, `scripts/`, `docs/`, and `plans/` as separate projects; `research/` is excluded due to worker memory limits.
- [x] Search queries return results on both backends.
- [x] Stdio fallback file is in place.
- [ ] 24-hour memory soak (pending).
- [ ] `detect_changes` validation after a small edit (pending).

## Residual Risks

1. **Bridge/gateway reliability**: `mcp-gateway` is a single point of failure. Mitigation: pinned v3.3.2, healthcheck, stdio fallback.
2. **Client HTTP support**: older clients may not support HTTP MCP. Mitigation: stdio fallback.
3. **Index drift**: on-demand containers may be stale. Mitigation: `mcp-status.sh` and `mcp-index.sh`.
4. **Resource contention**: GitNexus can consume RAM. Mitigation: 2 GB limit, 1 CPU.
5. **License**: `gitnexus` and `mcp-gateway` are PolyForm Noncommercial. Commercial use requires licenses. Prefer `codebase-memory-mcp` (MIT).
6. **cbm full-repo memory limit**: `research/` contains large JSON/JSONL/CSV files that blow past the cbm worker's per-process memory budget (~1 GB on this Docker host). The crash is a SIGKILL from the supervisor/OOM watchdog, not a parser bug. Mitigation: split code directories into separate projects; use GitNexus for full-repo queries; consider raising Docker Desktop's memory limit if a single cbm project is required.
7. **GitNexus index in repo**: `.gitnexus/` is created inside the working tree (ignored by `.gitignore`). Monitor disk usage.

## Historical Context

The original design notes below are retained for traceability.

## Original Design Notes (Pre-implementation)

## Options Considered

### Option A: Local Process Supervisor
Run each MCP server under `systemd` (Linux) / `launchd` (macOS) as a user service with `ExecStop` and restart-on-failure.

- **Pros:** Fastest to implement, no Docker overhead.
- **Cons:** Platform-specific, still leaves orphaned children if the supervisor is not the MCP server’s direct parent, and does not solve the `npx` shim problem for GitNexus. Does not isolate the LadybugDB/SQLite state.

### Option B: Docker Containers with HTTP/SSE MCP via `supergateway`
Run each server in a dedicated container. For stdio-native servers, add a small stdio-to-SSE bridge (`supergateway` or `mcp-proxy`). Clients connect to `http://localhost:<port>/sse`.

- **Pros:** Clean lifecycle (`docker compose down` kills the whole process tree), isolated state volumes, reusable across all agents, portable, consistent with the existing `docker-compose.yml`.
- **Cons:** One bridge per server; requires explicit port mapping; minimal observability.

### Option C: Docker Containers with `mcp-gateway` as a Multi-Backend Router
Run a single `mcp-gateway` container that registers both `codebase-memory-mcp` and `gitnexus` as stdio backends and exposes them on direct backend routes (`/mcp/cbm`, `/mcp/gitnexus`).

- **Pros:** One container instead of two bridges, built-in health checks and circuit breakers, reduces tool-list token overhead for agents, supports stdio/SSE/HTTP/WebSocket natively.
- **Cons:** Adds a PolyForm Noncommercial dependency (commercial use requires a license); changes the operational surface to a gateway config (`gateway.yaml`).

### Option D: Docker Containers with `IBM/mcp-context-forge`
Run ContextForge as a full AI gateway with PostgreSQL and Redis.

- **Pros:** Apache 2.0 license, enterprise governance, observability, UI.
- **Cons:** Heavyweight for two local MCP servers (300+ env vars, needs PG/Redis/nginx), production images do not support arm64, conflicts with the repo’s existing infrastructure discipline.

### Bridge/Gateway Alternatives Analysis

| Dimension | `supergateway` | `MikkoParkkola/mcp-gateway` | `IBM/mcp-context-forge` |
|---|---|---|---|
| License | Likely MIT/permissive | PolyForm Noncommercial | Apache 2.0 |
| Scope | Single-server stdio↔SSE bridge | Multi-backend MCP router | Enterprise AI gateway |
| Containers needed | 2 (one per MCP server) | 1 gateway + backends inside | Gateway + PG + Redis + nginx |
| Resource footprint | Tiny | Small (~12 MB Rust binary) | Large (Python FastAPI stack) |
| Health checks / CB | Minimal | Built-in | Built-in |
| Agent tool surface | Unchanged | Unchanged in direct-route mode | Changed (governed surface) |

**Selected bridge:** `mcp-gateway` (Option C). It replaces two bridge containers with one, fits the repo’s resource limits, and keeps the original tool schemas when using direct backend routes. `supergateway` remains the simpler fallback if the `mcp-gateway` license is a blocker. ContextForge is rejected as overkill for this local code-intelligence use case.

### Selected Design: Option C
Docker containers with a single `mcp-gateway` router are the best fit because the repo already standardizes on Docker Compose for infrastructure, the goal is **process containment**, and one gateway container is simpler than managing two separate bridges.

## Selected Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host (macOS/Linux)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────────┐   │
│  │ VS Code     │  │ Claude Code │  │ Codex CLI / Cursor    │   │
│  │  mcp.json   │  │  mcp.json   │  │  mcp.json / hooks     │   │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬───────────┘   │
│         │                │                      │               │
│         └────────────────┴──────────────────────┘               │
│                          │                                      │
│          HTTP/SSE MCP endpoints                                 │
│          http://localhost:9747/mcp/cbm   (codebase-memory)    │
│          http://localhost:9747/mcp/gitnexus (gitnexus)        │
│                          │                                      │
│  ┌───────────────────────┴───────────────────────┐              │
│  │           docker compose -f mcp-compose.yml   │              │
│  │  ┌─────────────────────────────────────────┐ │              │
│  │  │         mcp-gateway container           │ │              │
│  │  │  ┌──────────────┐  ┌─────────────────┐ │ │              │
│  │  │  │ cbm backend  │  │ gitnexus backend│ │ │              │
│  │  │  │ (stdio)      │  │ (stdio)         │ │ │              │
│  │  │  └──────────────┘  └─────────────────┘ │ │              │
│  │  │  port: 9747                              │ │              │
│  │  │  cbm cache volume                        │ │              │
│  │  │  gitnexus cache volume                   │ │              │
│  │  └─────────────────────────────────────────┘ │              │
│  └───────────────────────────────────────────────┘              │
│                                                                 │
│  Fallback: local stdio (current .vscode/mcp.json kept as backup)│
└─────────────────────────────────────────────────────────────────┘
```

## Container Design

### Gateway Container: `mcp-gateway`

`mcp-gateway` runs as a single container. It spawns both stdio backends internally and exposes them on direct backend routes.

- **Base image:** `debian:bookworm-slim` or a minimal image with the Rust binary installed.
- **Binary:** Download the official `mcp-gateway` release binary (e.g., `linux-amd64`) or install via `cargo binstall mcp-gateway`.
- **Port:** `9747` (gateway endpoint).
- **Config:** Mount `gateway.yaml` with the two backend definitions.
- **Volumes:**
  - Named volume `cbm-cache` → `/data/cbm` (`CBM_CACHE_DIR=/data/cbm`).
  - Named volume `gitnexus-cache` → `/data/gitnexus`.
  - Bind mount repo root `..:/workspace:ro` for indexing.
  - Bind mount `./mcp/gateway.yaml:/config/gateway.yaml:ro`.
- **Environment:**
  - `CBM_CACHE_DIR=/data/cbm`
  - `GITNEXUS_HOME=/data/gitnexus`
- **Healthcheck:** `curl -f http://localhost:9747/health`.
- **Resource limit:** 1 GB RAM, 0.5 CPU for the gateway; backends share this budget.

Example `gateway.yaml`:

```yaml
server:
  host: 0.0.0.0
  port: 9747

backends:
  cbm:
    command: "codebase-memory-mcp"
    description: "codebase-memory-mcp code intelligence"
    env:
      CBM_CACHE_DIR: "/data/cbm"
      CBM_LOG_LEVEL: "info"

  gitnexus:
    command: "gitnexus mcp"
    description: "GitNexus code intelligence"
    env:
      # gitnexus stores registry under $HOME/.gitnexus by default;
      # redirect to /data/gitnexus via env if supported, or symlink in entrypoint.
      HOME: "/data/gitnexus"
```

> Note: Confirm the exact environment variables `gitnexus` respects for registry path. If none, create a symlink in the entrypoint: `ln -s /data/gitnexus $HOME/.gitnexus`.

### New Compose File: `mcp-compose.yml`

A separate compose file keeps the MCP stack **on-demand** and out of the main quant services.

```yaml
services:
  mcp-gateway:
    build:
      context: ./mcp/gateway
    ports:
      - "127.0.0.1:9747:9747"
    volumes:
      - cbm-cache:/data/cbm
      - gitnexus-cache:/data/gitnexus
      - ./mcp/gateway.yaml:/config/gateway.yaml:ro
      - ..:/workspace:ro
    environment:
      - CBM_CACHE_DIR=/data/cbm
      - HOME=/data/gitnexus
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '0.5'
    networks:
      - mcp-net

volumes:
  cbm-cache:
  gitnexus-cache:

networks:
  mcp-net:
    driver: bridge
```

> Note: `..` in the volume path assumes `mcp-compose.yml` lives in a subdirectory. Use `${FLIPPER_REPO:-/Users/aloobhujia/flipperAgent}` or an env override for portability.

## Client Configuration

### Primary: HTTP MCP endpoints

Update `.vscode/mcp.json` (and equivalents for other agents):

```json
{
  "servers": {
    "mem0-local": {
      "type": "http",
      "url": "http://localhost:8889/mcp"
    },
    "codebase-memory-mcp": {
      "type": "http",
      "url": "http://localhost:9747/mcp/cbm"
    },
    "gitnexus": {
      "type": "http",
      "url": "http://localhost:9747/mcp/gitnexus"
    }
  }
}
```

Direct backend routes keep the original tool names/schemas, so agents do not need to use `gateway_search_tools` / `gateway_invoke`.

### Fallback: Stdio (kept but disabled by default)

Keep the original stdio entries in a separate file (e.g., `.vscode/mcp.json.stdio-fallback`) so a user can rename it if the Docker stack is down. Document the switch.

## Fallback Policies

The plan defines three operational layers.

### Layer 1 — Primary: Containerized HTTP/SSE via `mcp-gateway`
- Start: `docker compose -f mcp-compose.yml up -d`
- Stop: `docker compose -f mcp-compose.yml down`
- Restart: `docker compose -f mcp-compose.yml restart mcp-gateway`
- Index commands:
  - `codebase-memory-mcp`: `docker compose -f mcp-compose.yml exec mcp-gateway codebase-memory-mcp cli index_repository '{"repo_path": "/workspace"}'`
  - `gitnexus`: `docker compose -f mcp-compose.yml exec mcp-gateway gitnexus analyze /workspace --force`

### Layer 2 — Fallback: Local Stdio
If Docker is unavailable or the bridge fails, switch to the current `.vscode/mcp.json` stdio configuration.
- Trade-off: reintroduces the dangling-process risk, but only as a temporary fallback.
- Trigger: container healthcheck fails for > 60 seconds.

### Layer 3 — Emergency: Direct CLI
For one-off queries when both containers and stdio are broken:
- `codebase-memory-mcp cli ...` (local binary)
- `npx gitnexus analyze` / `npx gitnexus cypher` (local npx)

This layer is intentionally manual and not part of the agent MCP config.

## Operational Runbooks

### Dangling Process Cleanup (before migration)
```bash
# macOS: find and kill orphaned processes
pgrep -f "codebase-memory-mcp" | xargs kill -9
pgrep -f "gitnexus" | xargs kill -9
pgrep -f "ladybug" | xargs kill -9
```

### Container Soak / Validation
- Run `docker compose -f mcp-compose.yml up -d` for 24 hours.
- Capture `docker stats` and `cbm-diagnostics` (for `codebase-memory-mcp`) to verify no leaks.
- Re-index after a small code change and confirm `detect_changes` works on both.

### Index Rebuild (since selected choice is "Rebuild from scratch")
1. `docker compose -f mcp-compose.yml down -v` (clears named volumes)
2. `docker compose -f mcp-compose.yml up -d`
3. Run index commands for both tools.
4. Verify with `list_projects` / `list_repos`.

## Affected Files & New Files

### New files
- `mcp-compose.yml`
- `mcp/gateway/Dockerfile`
- `mcp/gateway/entrypoint.sh`
- `mcp/gateway.yaml`
- `mcp/scripts/mcp-cleanup.sh` (dangling-process cleanup)
- `mcp/scripts/mcp-status.sh` (health + index status)
- `.vscode/mcp.json` (updated to HTTP endpoints)
- `.vscode/mcp.json.stdio-fallback` (retained backup)
- `docs/mcp-fallback.md` (runbook)

### Modified files
- `.gitignore` — add `mcp/cbm/cbm-cache` if any local cache is used, and ignore bridge `node_modules` if built locally.
- `AGENTS.md` — add a note that the repo is indexed via containerized MCP and point to the runbook.

## Implementation Order

1. **Bridge spike**: Verify `mcp-gateway` can register both `codebase-memory-mcp` and `gitnexus mcp` as stdio backends and route direct backend requests locally.
2. **Dockerfile**: Create `mcp/gateway/Dockerfile` installing `mcp-gateway`, `codebase-memory-mcp`, and `gitnexus`.
3. **Config**: Create `mcp/gateway.yaml` with the two backend definitions.
4. **Compose**: Create `mcp-compose.yml` with healthchecks and resource limits.
5. **Client switch**: Update `.vscode/mcp.json` to HTTP endpoints; create `.vscode/mcp.json.stdio-fallback`.
6. **Scripts**: Add `mcp/scripts/mcp-cleanup.sh` and `mcp/scripts/mcp-status.sh`.
7. **Soak**: Run the gateway container for 24 hours; confirm no dangling processes and that both backends respond.
8. **Re-index**: Rebuild both indexes from scratch in the container volumes.
9. **Documentation**: Write `docs/mcp-fallback.md`.

## Acceptance Criteria

- [ ] `docker compose -f mcp-compose.yml up -d` starts the gateway container and the `/health` endpoint passes.
- [ ] VS Code Copilot can call tools from both `codebase-memory-mcp` and `gitnexus` over their direct backend HTTP endpoints.
- [ ] `docker compose -f mcp-compose.yml down` leaves no `codebase-memory-mcp`, `gitnexus`, `mcp-gateway`, `node`, `lbug`, or `cbm` processes on the host.
- [ ] Re-indexing both tools from scratch succeeds and produces non-empty graphs.
- [ ] `detect_changes` on both tools returns meaningful affected symbols after a small code edit.
- [ ] The stdio fallback file is documented and can be activated in under 60 seconds.
- [ ] A 24-hour soak shows stable memory usage (no monotonic RSS growth in gateway or backend diagnostics).

## Residual Risks

1. **Bridge/gateway reliability**: `mcp-gateway` may itself become a failure point. Mitigation: pin version, add healthcheck, and keep stdio fallback.
2. **Client HTTP support**: Some agents (e.g., older Cursor builds) may not support HTTP MCP. Mitigation: keep stdio fallback and test each client.
3. **Index drift**: With on-demand containers, users may forget to restart/reindex after code changes. Mitigation: add a `mcp/scripts/mcp-status.sh` that reports staleness and integrate a post-commit hook if acceptable.
4. **Resource contention**: GitNexus LadybugDB can consume large RAM. Mitigation: set `deploy.resources.limits.memory` and monitor; swap to on-demand profile if needed.
5. **License**: Both `gitnexus` and `mcp-gateway` default to PolyForm Noncommercial. Commercial quant use of either requires a paid license. Mitigation: confirm license status for both tools; prefer `codebase-memory-mcp` (MIT) as the primary code-intelligence source.
6. **Backend route availability**: Direct backend routes (`/mcp/cbm`, `/mcp/gitnexus`) must be verified against the exact `mcp-gateway` version. Mitigation: test route discovery after installation and adjust `gateway.yaml` if the path format changes.

## Unresolved Decisions

- The user selected all client options; confirm whether Cursor or any other stdio-only client is actually in use. If so, keep the stdio fallback path permanently.
- Final port numbers (`9748`, `4748`) are suggestions; verify they do not conflict with existing services in the main compose file.
- Pinned versions of `supergateway`, `codebase-memory-mcp`, and `gitnexus` should be locked in Dockerfiles and updated via Dependabot/ Renovate.
