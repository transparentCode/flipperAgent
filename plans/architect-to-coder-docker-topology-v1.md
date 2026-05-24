---
goal: 'Design Phase 5: Docker Containerization Architecture'
stage: 'architect-to-coder'
date_created: '2026-05-23'
owner: 'Quant Research Architect'
status: 'Ready'
tags: ['handoff', 'quant', 'infrastructure', 'docker', 'compose']
target_agent: 'Coder Agent'
---

# Docker Topology Handoff v1

## Objective
Establish the local development and deployment environment for the ingestion pipeline using Docker and docker-compose. Implement the approved 5-container topology: TimescaleDB (relational/time-series storage), Valkey (broker/queue), plus three application containers (scheduler, worker-queue, worker-streams) that run the `flipperAgent` ingestion codebase.

## Scope Boundaries
- Creates a root `Dockerfile` optimized for Python (dependency installation via `pyproject.toml` / dependencies).
- Creates a `.dockerignore`.
- Creates a `docker-compose.yml` defining the 5 requested services, configuring networking, dependencies, and environment variables.
- Configures local volume bind mounts for ephemeral JSONL storage (`./data:/app/data`).

## Affected Symbols, Modules, and Execution Flows
- **New Files**: `Dockerfile`, `.dockerignore`, `docker-compose.yml`.

## Data Contracts or Interfaces
- **Environment Variables**:
  - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
  - `POSTGRES_URI`: Connecting app to `timescaledb` internally (e.g., `postgresql://user:pass@db:5432/flipper`).
  - `REDIS_URI` / `VALKEY_URI`: App -> Broker (e.g., `redis://broker:6379/0`).
- **Volumes**:
  - `timescaledb-data`: Docker volume.
  - `valkey-data`: Docker volume.
  - `./data:/app/data`: Local bind mount for the JSONL backups so we can inspect locally.

## Implementation Order
1. **Dockerfile**: Create a multi-stage Python 3.11 Dockerfile. Ensure it runs `pip install .` or `pip install -r requirements.txt`.
2. **.dockerignore**: Exclude `.venv/`, `__pycache__`, etc.
3. **docker-compose.yml**:
   - `db`: `timescale/timescaledb:latest-pg15` (named volume, port 5432).
   - `broker`: `valkey/valkey:latest` (named volume, port 6379).
   - `worker-queue`: Local build, runs `arq flipper_agent.ingestion.orchestration.worker.WorkerSettings`. Depends on `db` and `broker`.
   - `worker-streams`: Local build, runs entrypoint for websocket listener (can be a dummy command or sleep if not yet unified).
   - `scheduler`: Local build, runs the cron dispatcher if standalone.

## Acceptance Criteria
- [ ] `docker-compose.yml`, `Dockerfile`, and `.dockerignore` are syntactically valid.
- [ ] Named volumes are properly mapped, protecting state across restarts.
- [ ] The JSONL ephemeral data zone relies on `./data:/app/data` cleanly.
