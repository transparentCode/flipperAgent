#!/bin/bash
# Convenience script to run staged Bayesian hyperparameter optimizations for BTCUSDT.

echo "======================================================"
echo "Starting Regimes Optimization for BTCUSDT (30m)"
echo "Dates: 2022-01-01 to 2026-01-01"
echo "======================================================"
python3 app/regime/scripts/run_optimization.py \
    --asset BTCUSDT \
    --timeframe 30m \
    --start-date 2022-01-01 \
    --end-date 2026-01-01 \
    --staged \
    --n-trials 150 \
    --stage1-trials 40 \
    --stage2-trials 40 \
    --stage3-trials 70 \
    --timeout 15000 \
    --n-jobs 1 \
    --step-bars 2160

echo ""
echo "======================================================"
echo "Starting Regimes Optimization for BTCUSDT (1h)"
echo "Dates: 2022-01-01 to 2026-01-01"
echo "======================================================"
python3 app/regime/scripts/run_optimization.py \
    --asset BTCUSDT \
    --timeframe 1h \
    --start-date 2022-01-01 \
    --end-date 2026-01-01 \
    --staged \
    --n-trials 150 \
    --stage1-trials 40 \
    --stage2-trials 40 \
    --stage3-trials 70 \
    --timeout 15000 \
    --n-jobs 1 \
    --step-bars 2160

echo "Done! The best parameters have been written to app/regime/config/regime.yaml"
