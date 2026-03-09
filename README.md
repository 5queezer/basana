[![Testcases](https://github.com/gbeced/basana/actions/workflows/runtests.yml/badge.svg?branch=master)](https://github.com/gbeced/basana/actions/workflows/runtests.yml)
[![PyPI version](https://badge.fury.io/py/basana.svg)](https://badge.fury.io/py/basana)
[![Read The Docs](https://readthedocs.org/projects/basana/badge/?version=latest)](https://basana.readthedocs.io/en/latest/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Downloads](https://static.pepy.tech/badge/basana/month)](https://pepy.tech/project/basana)

# Basana

**Basana** is a Python **async and event driven** framework for **algorithmic trading**, with a focus on **crypto currencies**.

## Key Features

* Backtesting exchange so you can try your trading strategies before using real funds.
* Live trading at [Binance](https://www.binance.com/) and [Bitstamp](https://www.bitstamp.net/) crypto currency exchanges.
* Asynchronous I/O and event driven.

## Getting Started

### Installation

```
$ pip install basana[charts]
```

The examples use [TALIpp](https://github.com/nardew/talipp) for the technical indicators, pandas, statsmodels and also [Textual](https://textual.textualize.io/) if you want to run the Binance order book mirror.

```
$ pip install talipp pandas statsmodels textual
```

Download and unzip [samples](https://github.com/gbeced/basana/releases/download/1.9/samples.zip) or clone the [GitHub](https://github.com/gbeced/basana/) repository.

### Backtest a pairs trading strategy

1. Download historical data for backtesting

	```
	$ python -m basana.external.binance.tools.download_bars -c BCH/USDT -p 1h -s 2021-12-01 -e 2021-12-26 -o binance_bchusdt_hourly.csv
	$ python -m basana.external.binance.tools.download_bars -c CVC/USDT -p 1h -s 2021-12-01 -e 2021-12-26 -o binance_cvcusdt_hourly.csv
	```

2. Run the backtest

	```
	$ python -m samples.backtest_pairs_trading
	```

![./docs/_static/readme_pairs_trading.png](./docs/_static/readme_pairs_trading.png)

### Binance Order Book mirror

The following example demonstrates how to maintain a synchronized local copy of a Binance order book using Basana's event-driven architecture. It initializes the order book from a REST API snapshot, then continuously updates it with real-time diffs from a WebSocket stream while periodically verifying consistency against fresh snapshots to handle potential synchronization issues.

![./docs/_static/order_book_mirror.png](./docs/_static/order_book_mirror.png)

Use the following command to run the example:

```
$ python -m samples.binance_order_book_mirror
```

The mirroring code can be found [here](./samples/binance/order_book_mirror.py).

The Basana repository comes with a number of [examples](./samples) you can experiment with or use as a template for your own projects:

**Note that these examples are provided for educational purposes only. Use at your own risk.**

## Quant Abstraction Groundwork

A small Basana-native quant foundation now lives in `basana.quant`.

This slice is intentionally **generic** and keeps repository boundaries clean: it provides framework abstractions and offline examples, but no source-specific adapters.

Included in this pass:

* `NormalizedSignal`: normalized signal schema for strategy outputs.
* `SignalSourcePlugin` + `SignalSourcePluginAdapter`: plugin interface and adapter that turn plugin output into Basana events.
* `ScheduledSignalPlugin`: generic queued-signal scheduling over bar events.
* `RankedTableSignalPlugin` / `parse_ranked_table_signals`: turns a simple ranked markdown table into normalized long signals.
* `ActionTextSignalPlugin` / `parse_action_text_signals`: turns compact action-oriented text alerts into normalized signals.
* `PortfolioRiskManager`: enforces `max_positions` and `max_gross_exposure`.
* `PaperSimulationEngine`: lightweight paper/backtest loop that marks positions to market from bar events.
* Runnable offline sample: `python3 -m samples.private_quant_backtest`

The sample uses generic fixture-style signal inputs plus `samples/data/quant_btcusdt_day.csv`, so it runs without exchange credentials, API keys, or external downloads.

Run the focused tests with:

```
$ pytest -q tests/quant
```

Run the sample with:

```
$ python3 -m samples.private_quant_backtest
```

## Documentation

[https://basana.readthedocs.io/en/latest/](https://basana.readthedocs.io/en/latest/)

## Help

You can seek help with using Basana in the discussion area on [GitHub](https://github.com/gbeced/basana/discussions).
