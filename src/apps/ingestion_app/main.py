import uvicorn
from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

def main():
    config_manager = ConfigManager()

    log_level = config_manager.get("logging.level", default="INFO")
    configure_logging(
        level=log_level,
        enable_file_logging=True,
        console_format=config_manager.get("logging.console_format", "json"),
        log_file=config_manager.get("logging.log_file"),
    )
    
    logger = bind_logger(component=SystemComponent.DATA_INGESTION_ENGINE)
    
    # Read the host and port from the YAML configuration
    # defaults are provided just in case
    host = config_manager.get("ingestion.server.host", default="0.0.0.0")
    port = config_manager.get("ingestion.server.port", default=8001)

    logger.info(f"Starting Ingestion controller on {host}:{port}")

    # Programmatically launch the controller
    uvicorn.run("apps.ingestion_app.orchestration.controller:app", host=host, port=port)

if __name__ == "__main__":
    main()
