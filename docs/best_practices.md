# flipperAgent Best Practices & Architectural Guidelines

## 1. Project Structure (Src-Layout)
- All business logic lives inside `src/flipper_agent/`. 
- **Rule**: Never use generic top-level namespaces (e.g., `src/commons/` or `src/data_ingestion/`). Doing so creates high risk of namespace collisions with 3rd-party `pip` modules.

## 2. Telemetry & Logging
- **Dependencies**: No external logging transports (e.g., `logging_loki`). Keep `logger_utils.py` purely dependent on the Python standard library.
- **Default Behavior**: 
  - File outputs (`app.log`) are written as strict JSON lines for structured ingestion.
  - Automatically manages disk space by rotating log files natively at midnight (`TimedRotatingFileHandler`), retaining the last 10 days by default (defined in `constants.py`). No external cron job required.
  - Console outputs use ANSI colors based on log severity for developer ergonomics.
- **Context Injection**:
  - A `trace_id` is propagated via `contextvars.ContextVar`.
  - If a log is emitted without an active trace, a UUID is automatically generated and securely attached to the context.
  - All discrete domains must log via predefined markers in the `SystemComponent` Enum (e.g., `DATA_INGESTION_ENGINE`).
- **Usage Example (Best Practice)**:
  Always bind your module-level logger upon instantiation and pass the specific system component. Do not instantiate vanilla standard library `logging.getLogger`.
  ```python
  from flipper_agent.commons.logging.logger_utils import bind_logger
  from flipper_agent.commons.enums import SystemComponent

  # Module-level binding
  logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

  def run_workflow():
      # The bound logger automatically injects component and trace_id context into every print.
      logger.info("Starting ingestion workflow.")
  ```

## 3. Configuration Management
- Configurations are driven by `PyYAML` and `Pydantic` models, and hot-reloaded automatically by `watchdog`.
- **Concurrency & Thread Safety Strategy**:
  - **Lock-Free Reads**: The config manager does not use read-locks. It relies on the Python GIL's atomic pointer swapping (`self._state = new_state`) to instantly switch active configs in memory during a reload. This completely prevents read contention across I/O threads without locking overhead. Do *not* mutate the config dictionary in place.
  - **Singleton Mutex**: A standard `threading.Lock()` (`_lock`) prevents race conditions during global memory singleton initialization.
  - **Debounce Mutex**: A `_debounce_lock` wraps a 500ms debounce timer to prevent watchdog event storms (e.g., rapid consecutive saves from IDEs) from spawning duplicate thread pools.
  - **Subscriber Sequence Lock**: A `_subscription_lock` guarantees the list of event subscribers isn't mutated by one thread while another is notifying callbacks.
- **Resilience Mechanisms**: 
  - Malformed YAML (Poison Pills) will be trapped: the update drops, the last known good state is maintained, and an error is logged.
- **Callbacks**: Avoid callback hell. Configurations are polled dynamically. Only register pub/sub callbacks for stateful and expensive teardowns (e.g. database reconnection pools).
- **Usage Example (Best Practice)**:
  Demonstrates instantiating the singleton, retrieving validated configurations using Pydantic, and subscribing to hot-reload config changes.
  ```python
  from pydantic import BaseModel
  from flipper_agent.commons.config import ConfigManager

  class IngestionConfig(BaseModel):
      poll_interval: int
      max_retries: int

  # 1. Instantiate the singleton config manager
  config_manager = ConfigManager()

  # 2. Retrieve a validated Pydantic model by passing a dotted key path
  ingestion_config = config_manager.get_parsed("system.ingestion", IngestionConfig)
  print(f"Polling at {ingestion_config.poll_interval}s intervals.")

  # 3. Subscribe to hot-reload changes (ideal for stateful teardowns)
  def on_config_changed(new_value, old_value):
      print(f"Ingestion config updated from {old_value} to {new_value}")
      
  config_manager.subscribe("system.ingestion", on_config_changed)
  ```

## 4. Exception Handling
- **Rule**: Never throw bare `Exception`. Always inherit from `FlipperAgentError`.
- The base `FlipperAgentError` is uniquely designed to capture the active `trace_id` at the exact moment of instantiation. This ensures the crash context is permanently embedded in the exception object when traversing stack boundaries.
- **Usage Example (Best Practice)**:
  Demonstrates how to create a custom exception and access the auto-bound `trace_id`.
  ```python
  from flipper_agent.commons.exceptions import FlipperAgentError

  # 1. Define a domain-specific exception inheriting from FlipperAgentError
  class DataValidationFailedError(FlipperAgentError):
      """Raised when incoming market data fails schema validation."""

  def process_payload(payload: dict):
      if not payload.get("price"):
          # 2. Raise the error. The trace_id is captured automatically!
          raise DataValidationFailedError("Payload missing price field", context={"payload": payload})

  try:
      process_payload({})
  except DataValidationFailedError as e:
      # 3. Access contextual properties on the deeply-caught exception
      print(f"Failed with Trace ID: {e.trace_id}")
      print(f"Context payload: {e.context}")
  ```