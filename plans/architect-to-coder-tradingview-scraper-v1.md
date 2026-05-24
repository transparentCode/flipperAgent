# Architect-to-Coder Handoff: TradingView Stealth Scraper

## Overview
This document outlines the architecture and execution plan for building a stealth web scraping adapter module to extract proprietary TradingView indices (e.g., `TOTAL2`, `TOTAL3`) directly from TradingView's Chart WebSocket feeds.

## Rationale
Institutional aggregators do not natively host these exact calculated indices, and third-party scrapers (like `tvDatafeed`) are brittle. We will implement robust WebSocket interception via `Scrapling` (a modern stealth framework) to ensure raw data availability when public APIs are absent, natively bypassing Cloudflare/Turnstile.

## Architecture Guidelines
1.  **Stealth Context via Scrapling**: Implement headless browser navigation using `Scrapling`'s `StealthySession` or `DynamicSession` to handle Cloudflare Turnstile bypass inherently, rather than relying on brittle `playwright-stealth` patches.
2.  **Authentication/Context Injection**: Store a valid exported TradingView session state (`auth_cookies.json`) and inject it into the session to bypass login UI limits. 
3.  **WebSocket Interception**: Do not attempt to OCR or scrape DOM elements. Use the underlying browser context to intercept traffic at `wss://data.tradingview.com/socket.io/` or equivalent.
4.  **Protocol Decoding**: The adapter must parse the custom TradingView socket.io framing (e.g. `~m~[length]~m~[json_payload]`).


## Scope Boundaries & Proposed Modules
*   Create an advanced ingestion adapter within `src/flipper_agent/ingestion/adapters/`.
*   Module: `tradingview_socket_interceptor.py`
*   Data Contracts: The module must yield a standard `DataFrame` or `List[Dict]` containing `[timestamp, open, high, low, close, volume]` mirroring the existing API-based connectors.

## Implementation Steps for Coder Agent
1.  **Setup Environment**: Add `scrapling[all]` (or `scrapling[fetchers]`) to toml/requirements, replacing traditional `playwright` and `playwright-stealth`.
2.  **Construct Base Adapter**: Create an async class `TradingViewInterceptor(BaseExchangeAdapter)` that initializes the `Scrapling` stealth browser (`AsyncStealthySession`).
3.  **Implement Cookie Loading**: Add a simple utility to load and inject cookies from `secrets/tv_cookies.json` to retain authenticated sessions.
4.  **WebSocket Listener**: Expose a standard async fetch method (e.g., `async def get_historical_ohlcv(symbol, timeframe)`) that uses the Scrapling page to navigate to the chart, intercepts the WSS traffic for the initial historical backfill payload, closes the context, and returns the formatted data.

## Explicit Non-Goals
*   Do not attempt to scrape custom Pine Script visual indicators yet; stick strictly to standard OHLCV volume arrays for native TV indices like `CRYPTOCAP:TOTAL2`.
*   Do not build a proxy rotational infrastructure in this module (assume proxy strings are provided as config ENV vars).
