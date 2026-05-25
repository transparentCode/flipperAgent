"""Shared dispatcher — delegates to per-model optimization scripts.

Usage:
    PYTHONPATH=src python scripts/run_optimization.py \
        --model MeanReversion --asset BTCUSDT --timeframe 1h --audit --write-back

Each model can also be invoked directly:
    PYTHONPATH=src python -m libs.models.mean_reversion.optimization.optimize --asset ...
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_MODEL_SCRIPTS: dict[str, str] = {
    "MeanReversion": "libs.models.mean_reversion.optimization.optimize",
    "TrendFollowing": "libs.models.trend_following.optimization.optimize",
    "Momentum": "libs.models.momentum.optimization.optimize",
}


def main() -> None:
    if "--model" not in sys.argv:
        print("Usage: run_optimization.py --model <ModelName> [other args...]")
        sys.exit(1)

    idx = sys.argv.index("--model")
    if idx + 1 >= len(sys.argv):
        print("Error: --model requires a value")
        sys.exit(1)

    model_name = sys.argv[idx + 1]

    if model_name not in _MODEL_SCRIPTS:
        print(f"Error: Unknown model '{model_name}'. "
              f"Available: {list(_MODEL_SCRIPTS.keys())}")
        sys.exit(1)

    sys.argv = [sys.argv[0]] + sys.argv[1:idx] + sys.argv[idx + 2:]
    module = importlib.import_module(_MODEL_SCRIPTS[model_name])
    module.main()


if __name__ == "__main__":
    main()
