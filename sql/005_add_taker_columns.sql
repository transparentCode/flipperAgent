-- Add taker volume columns to OHLCV table for microstructure indicators
-- (Kyle Lambda, TFI, VPIN require taker_buy_base)

ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS taker_buy_base FLOAT DEFAULT 0.0;
