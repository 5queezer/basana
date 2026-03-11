[![Testcases](https://github.com/5queezer/basana/actions/workflows/runtests.yml/badge.svg?branch=develop)](https://github.com/5queezer/basana/actions/workflows/runtests.yml)
[![PyPI version](https://badge.fury.io/py/basana.svg)](https://badge.fury.io/py/basana)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Downloads](https://static.pepy.tech/badge/basana/month)](https://pepy.tech/project/basana)

# Basana

**Basana** is a Python **async and event-driven** framework for **algorithmic trading**, with a focus on **cryptocurrency markets**.

This fork extends the upstream project with a more opinionated quant stack around:
- portfolio-level risk management,
- perpetuals trading infrastructure,
- paper-trading ledger + analytics,
- walk-forward evaluation,
- plugin architecture,
- and a Telegram bot control surface for live strategy monitoring.

## Key Features

- Backtesting exchange so you can test strategies before risking capital.
- Live trading support for [Binance](https://www.binance.com/), [Bitstamp](https://www.bitstamp.net/), and [Hyperliquid](https://hyperliquid.xyz/).
- Portfolio-level risk management with configurable limits:
  - max positions
  - exposure caps
  - correlation buckets
  - daily loss caps
  - kill switch
- First-class perpetuals support:
  - structured fills
  - funding rate tracking
  - mark price
  - liquidation distance monitoring
  - perp-specific risk limits (leverage, margin utilization)
- Paper-trading ledger with trade journal, equity curve tracking, and performance analytics:
  - Sharpe
  - Sortino
  - Calmar
  - drawdown
  - profit factor
- Walk-forward evaluation engine with expanding/sliding windows for time-safe strategy validation.
- Plugin architecture for strategy/runtime extensions.
- Telegram bot interface for monitoring and operational control.
- Fully asynchronous I/O and event-driven execution.

## Installation

### Minimal

```bash
pip install basana
```

### Common extras

```bash
pip install "basana[charts,telegram]"
```

### Hyperliquid support

```bash
pip install "basana[hyperliquid]"
```

### Everything commonly needed for local development

```bash
pip install "basana[charts,telegram,hyperliquid]"
pip install talipp pandas statsmodels textual
```

### Editable install from this fork

```bash
git clone https://github.com/5queezer/basana.git
cd basana
pip install -e ".[charts,telegram,hyperliquid]"
```

## Fork-specific additions

Compared with the upstream project, this fork includes major work in these areas:

- **Risk manager** (`basana.core.risk`)
- **Ledger + metrics** (`basana.core.ledger`)
- **Evaluation / walk-forward** (`basana.core.evaluation`)
- **Plugin system** (`basana.core.plugin`)
- **Hyperliquid connector** (`basana.external.hyperliquid`)
- **Telegram bot module** (`basana.external.telegram`)

## Telegram Bot Interface

The Telegram integration lives under `basana.external.telegram`.

### Included pieces

- `TelegramConfig`
- `TelegramBot`
- `Verbosity`
- auth guard / allowlist
- user rate limiting
- HTML formatters
- command handlers
- inline confirmation callbacks

### Supported built-in commands

- `/status`
- `/positions`
- `/risk`
- `/kill_switch`
- `/mode`

### Inline buttons

The Telegram module includes inline keyboard / confirmation flows for operational actions like:
- kill switch toggles
- deployment mode changes

If you want a more Cornix-style interactive trade UI, you will typically add strategy-specific buttons on top of the base module.

### Minimal example

```python
import basana as bs
from basana.external.telegram import TelegramBot, TelegramConfig, Verbosity

async def main():
    dispatcher = bs.realtime_dispatcher()

    telegram = TelegramBot(
        config=TelegramConfig(
            bot_token="<telegram-bot-token>",
            authorized_user_ids=[123456789],
            verbosity=Verbosity.NORMAL,
        ),
        event_dispatcher=dispatcher,
        risk_manager=my_risk_manager,
    )

    await dispatcher.run()
```

> Note: the built-in `/status`, `/positions`, `/risk`, `/kill_switch`, and `/mode`
> handlers expect a configured `RiskManager` when those commands need portfolio/risk state.

## Quick Examples

### Backtest a pairs trading strategy

1. Download historical data:

```bash
python -m basana.external.binance.tools.download_bars -c BCH/USDT -p 1h -s 2021-12-01 -e 2021-12-26 -o binance_bchusdt_hourly.csv
python -m basana.external.binance.tools.download_bars -c CVC/USDT -p 1h -s 2021-12-01 -e 2021-12-26 -o binance_cvcusdt_hourly.csv
```

2. Run the backtest:

```bash
python -m samples.backtest_pairs_trading
```

![./docs/_static/readme_pairs_trading.png](./docs/_static/readme_pairs_trading.png)

### Binance order book mirror

```bash
python -m samples.binance_order_book_mirror
```

Code: [`samples/binance/order_book_mirror.py`](./samples/binance/order_book_mirror.py)

### Hyperliquid sample

```bash
python -m samples.hyperliquid.rsi_strategy
```

## Source Layout

- `basana/core/` — dispatcher, risk, ledger, evaluation, plugins, strategies
- `basana/external/` — exchange connectors and integrations
- `samples/` — runnable examples and integration demos
- `docs/` — Sphinx docs and reference material
- `tests/` — test suite

## Documentation

- Hosted docs: [https://basana.readthedocs.io/en/latest/](https://basana.readthedocs.io/en/latest/)
- Fork source of truth: [`docs/`](./docs) and [`samples/`](./samples)

If hosted docs ever lag behind the fork, prefer the repository docs and code.

## Help

- Repository: [https://github.com/5queezer/basana](https://github.com/5queezer/basana)
- Issues / discussions: use this fork’s GitHub repository

## Safety note

These examples are provided for educational and research purposes.
Use at your own risk.
