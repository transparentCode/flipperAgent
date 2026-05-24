# Architect to Coder Handoff: Service-Oriented Monorepo Refactor

## 1. Intent & Scope
**Objective:** Restructure the existing codebase into a strict "Service-Oriented Monorepo" layout to support independent microservices sharing data over Valkey.
**Scale/Depth:** This phase is **STRICTLY limited to folder restructuring, import fixing, and CI/CD alignment.** No new quantitative features (RSI/ATR) or Valkey streams consumer loops will be built in this phase.

## 2. Target Directory Structure
The codebase must be reorganized from the existing `src/flipper_agent/` layout into the following explicit boundaries:

```text
flipperAgent/
├── apps/
│   └── ingestion_app/       # Moved from src/flipper_agent/ingestion/
│       ├── main.py
│       └── ...
├── libs/
│   ├── common/              # Moved from src/flipper_agent/commons/
│   │   ├── config/
│   │   ├── logging/
│   │   ├── db/
│   │   └── exceptions/
│   ├── contracts/           # New empty folder for shared Pydantic schemas/topics
│   ├── valkey_bus/          # New empty folder for Valkey stream clients
│   └── features/            # New empty folder for the future Math core
└── tests/
    ├── e2e/                 
    └── ingestion/           
```

## 3. Required Implementation Steps

### Phase 1: Physically Move Files
- [ ] Create the top-level `apps/` and `libs/` directories (you may place them at the root, or within `src/` depending on standard Python packaging, but ensure the namespace is cleanly `apps.*` and `libs.*`).
- [ ] Migrate all Ingestion logic into `apps/ingestion_app/`.
- [ ] Migrate all Shared utilities (DB, logging, config) into `libs/common/`.
- [ ] Create placeholder directories for `libs/contracts/`, `libs/valkey_bus/`, and `libs/features/`.

### Phase 2: Fix Pointers and Imports
- [ ] Update all intra-project Python `import` statements to reflect the new `apps.` and `libs.` namespaces.
- [ ] Update `docker-compose.yml` build contexts, commands, and volumes to map correctly to the relocated `ingestion_app` entry points.
- [ ] Update paths in `pyproject.toml`, `Dockerfile`, and testing scripts (`tests/e2e/run_e2e_tests.sh`).

### Phase 3: Validation and Verification
- [ ] Execute `pytest` for the unit tests and fix any `ModuleNotFoundError`s.
- [ ] Run the full Docker E2E suite (`./tests/e2e/run_e2e_tests.sh`). 

## 4. Exit Criteria & Constraints
The system must compile, the Docker containers must boot, and the E2E ingestion websocket integrations must pass identically to how they did prior to the refactor. **Zero new feature engineering logic should be written; this is a pure structural migration.** Future modules (Features, Signal Engine) will be planned and implemented only after this refactor completes.
