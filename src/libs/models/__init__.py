# Auto-discover all concrete models so they self-register.
from libs.models.registry import ModelRegistry

ModelRegistry.auto_discover()
