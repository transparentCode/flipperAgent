"""Shared JSON encoder for numpy/datetime types."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np


class NumpyDatetimeEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy scalars/arrays and datetime objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)
