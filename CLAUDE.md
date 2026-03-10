# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Basana is an async, event-driven Python framework for algorithmic trading. It supports backtesting and live trading on Binance, Bitstamp, and Hyperliquid exchanges.

## Common Commands

```bash
# Setup
poetry install --all-extras

# Run all checks (lint + test)
inv test

# Lint only (mypy + ruff)
inv lint

# Test only
poetry run pytest -vv --cov --cov-config=setup.cfg --durations=10

# Run a single test file
poetry run pytest tests/test_backtesting_orders.py -vv

# Run a single test
poetry run pytest tests/test_backtesting_orders.py::test_name -vv

# Type checking
poetry run mypy basana

# Linting
poetry run ruff check

# Build docs
inv build-docs
```

## Architecture

### Event-Driven Core (`basana/core/`)

Everything flows through an event dispatch loop. `EventDispatcher` (with `BacktestingDispatcher` and `RealtimeDispatcher` variants) drives the system by pulling events from prioritized `EventSource` instances.

Key flow: Data sources emit `BarEvent`s → Strategies process bars and emit `TradingSignal`s → `RiskManager` filters signals through risk limits → `PositionManager` converts approved signals into orders on an `Exchange`.

### Risk Management (`basana/core/risk/`)

Portfolio-level risk controls sitting between strategies and execution. `RiskManager` is a `FifoQueueEventSource` that filters `TradingSignal`s through a chain of `RiskLimit` checks. Built-in limits: `MaxPositionsLimit`, `MaxGrossExposureLimit`, `CorrelationBucketLimit`, `DailyLossCapLimit`, `PerTradeRiskSizer`. Supports `DeploymentMode` (MONITOR/PAPER/LIVE) and a kill switch. `PortfolioTracker` maintains position state from fills and price updates.

### Exchange Abstraction

The same strategy code runs against both backtesting and live exchanges:

- **`basana/backtesting/`** — Simulated exchange with order matching, balance tracking, fee calculation, liquidity/slippage modeling, and margin lending simulation.
- **`basana/external/`** — Live connectors (Binance, Bitstamp, Hyperliquid) wrapping REST APIs and WebSocket streams.

Each exchange connector follows the same pattern: `exchange.py` (main entry), `client/` (REST API), `websockets.py` (real-time streams), and domain-specific modules (e.g., `spot.py`, `margin.py`, `perps.py`).

### Shared Utilities (`basana/external/common/`)

Cross-exchange utilities, primarily CSV bar loading.

## Code Conventions

- **All financial values use `Decimal`, never `float`.**
- **All datetimes must be timezone-aware** (enforced by assertions). Use `utc_now()` / `local_now()` from `basana.core.dt`.
- **Frozen dataclasses** for immutable value objects (`Pair`, `Bar`, `OrderInfo`, etc.).
- **Fully async** — event handlers and exchange methods are all `async`.
- **100% test coverage required** — builds fail below 100%. Use `# pragma: no cover` sparingly.

## Pre-commit Hooks

Configured in `.pre-commit-config.yaml`: secrets detection (detect-secrets, detect-private-key), code quality checks, ruff (lint + format), and bandit (security scanning, excludes tests).

## CI

Tests run on Python 3.10–3.14, on Ubuntu and macOS. Pipeline: `mypy basana` → `ruff check` → `pytest` with coverage.
