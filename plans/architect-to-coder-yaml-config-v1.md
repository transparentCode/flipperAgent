# Architect to Coder Handoff: Asset-Timeframe YAML Configuration

## 1. Intent & Scope
**Objective:** Decouple indicator hyperparameters from the source code. Move all configuration into a centralized YAML hierarchy where every Asset and Timeframe can possess its own tailored indicator parameters. 
**Scale/Depth:** Create the core YAML schema, build a configuration loader in `libs/features`, and ensure it natively aligns with the `IndicatorRegistry` designed in previous steps.

## 2. Directory Structure Target
```text
/config
  features.yaml           <-- The new centralized config file
/src/libs/features
  config_loader.py        <-- The parser and retrieval logic
```

## 3. High-Level Requirements

### A. The YAML Schema (`configs/features.yaml`)
Design a structured schema that explicitly scales down from Asset -> Timeframe -> Indicator -> Parameters.
Example format:
```yaml
assets:
  "BTC/USD":
    timeframes:
      "1h":
        RSI:
          period: 14
        MACD:
          fast_period: 12
          slow_period: 26
          signal_period: 9
      "15m":
        RSI:
          period: 21
  "ETH/USD":
    timeframes:
      "1h":
        RSI:
          period: 12
```

### B. The Config Loader (`config_loader.py`)
- **Parser:** Build a `FeatureConfigLoader` class that reads the YAML using `pyyaml` or `ruamel.yaml`.
- **Retrieval Math:** Implement a method like `get_indicator_params(asset: str, timeframe: str, indicator_name: str) -> dict`.
- **Fallback Logic:** Implement fallback logic if an asset/timeframe combo doesn't exist (e.g., fall back to a `default` asset/timeframe tree or raise a clean `ConfigError`).

### C. Registry Instantiation 
- Ensure that the dictionary returned by the config loader can be unpacked directly into the indicator instantiation:
  `params = loader.get_indicator_params("BTC/USD", "1h", "RSI")`
  `rsi_instance = IndicatorRegistry.get("RSI")(**params)`

## 4. Parity/Testing Requirements
- Create `tests/integration/features/test_config_loader.py`
- Test parsing a dummy YAML file.
- Verify that unpacking dictionary `**params` safely builds the required indicators (like EMA and Bollinger) through the `IndicatorRegistry`.
