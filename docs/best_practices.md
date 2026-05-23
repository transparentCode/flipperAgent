# flipperAgent Best Practices & Architectural Guidelines

## 1. Project Structure (Src-Layout)
- All business logic lives inside `src/flipper_agent/`. 
- **Rule**: Never use generic top-level namespaces (e.g., `src/commons/` or `src/data_ingestion/`). Doing so creates high risk of namespace collisions with 3rd-party `pip` modules.

## 2. Telemetry & Logging
- **Dependencies**: No external logging transports (e.g., `logging_loki`). Keep `logger_utils.py` purely dependent on Python standard library.
- **Format**: File outputs (`app.log`) are strict JSON lines for structured ingestion. Console outputs use ANSI colors based on log severity for developer ergonomics.
- **Context Injection**:
  - A `trace_id` is propagated via `contextvars.ContextVar`.
  - If a log is emitted without an active trace, a UUID is automatically generated and securely attached to the context.
  - All discrete domains must log via predefined markers in the `SystemComponent` Enum.

## 3. Configuration Management
- Configurations are driven by `PyYAML` and `Pydantic` models, and hot-reloaded automatically by `watchdog`.
- **Thread Safety**: The config manager uses atomic pointer swapping. Do *not* mutate the config dictionary in place.
- **Resilience Mechanisms**: 
  - A 500ms debounce prevents crashing on half-written files from editors like VS Code.
  - Malformed YAML (Poison Pills) will be trapped: the update drops, the last known good state is maintained, and an error is logged.
- **Callbacks**: Avoid callback hell. Configurations are polled dynamically by infinite loops. Only register pub/sub callbacks for stateful and expensive teardowns (e.g. database reconnection pools).

## 4. Exception Handling
- **Rule**: Never throw bare `Exception`. Always inherit from `FlipperAgentError`.
- The base `FlipperAgentError` is uniquely designed to capture the active `trace_id` at the exact moment of instantiation. This ensures the crash context is permanently embedded in the exception object when traversing stack boundaries.