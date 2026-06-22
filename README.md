# Beecthor Perps

Dedicated automation workspace for testing Beecthor-derived BTCUSDC and BTCUSDT perpetual futures strategies.

The repo is intentionally conservative:

- `shadow` mode is the default and never sends exchange orders.
- `testnet` must be explicit.
- `mainnet` is blocked unless a dedicated subaccount and real-money acknowledgement are configured.
- Strategy output is an order intent, not an order, until it passes deterministic safety checks.
- BTCUSDC and BTCUSDT order sizes start at the practical minimum that satisfies each Binance Demo symbol's filters; at recent BTC prices this is usually `0.002 BTC`.
- Multi-position support is explicit: `POSITION_MODE=hedge` requires Binance Hedge Mode to already be enabled and flat before switching.

## Quick Start

```powershell
cd E:\Software\Coding\beecthor-perps
$env:PYTHONPATH="$PWD\src"
python -m unittest
python -m beecthor_perps status
python -m beecthor_perps evaluate --thesis examples\beecthor_thesis.sample.json --price 78100
python -m beecthor_perps check-telegram
python -m beecthor_perps position-mode status
python -m beecthor_perps list-active-trades
python -m beecthor_perps run-engine --once
```

Or install it editable:

```powershell
python -m pip install -e .
beecthor-perps status
```

## Phases

1. `shadow`: parse theses, produce decisions, write no exchange orders.
2. `testnet`: send orders only to Binance USD-M Futures testnet.
3. `mainnet`: disabled unless all real-money guardrails are explicitly satisfied.

## V1 Flow

`beecthor-summary` owns the LLM step. When the daily Beecthor transcript is summarized, it also writes a safe operable thesis to `data/perps_theses/latest.json`.

`beecthor-perps` owns execution and risk. Configure `BEECTHOR_THESIS_FILE` to point at that `latest.json`; the engine then:

- loads the latest thesis
- waits for a closed 5m reclaim/rejection
- validates reward/risk, stop, take-profit, notional, leverage, and symbol
- places the entry only in Binance Demo/Testnet
- immediately places exchange-native conditional algo stop-loss and take-profit orders
- sends Telegram notifications for open, TP, SL, unknown close, and critical protection failures

Telegram notifications reuse the existing BeecthorDaily bot through `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Secrets stay in `.env`, never in Git.

## Safety Contract

The bot must refuse to trade when any of these are true:

- symbol is outside `SYMBOL_ALLOWLIST`
- notional is above `MAX_NOTIONAL_USDC`
- leverage is above `MAX_LEVERAGE`
- stop loss or take profit is missing
- stop/take-profit direction is invalid
- there is already an open position beyond `MAX_OPEN_POSITIONS`
- one side already has `MAX_OPEN_POSITIONS_PER_SIDE`
- aggregate tracked notional would exceed `MAX_TOTAL_NOTIONAL_USDC`
- a long in One-way Mode would reduce an existing short, or a short would reduce an existing long
- daily realized loss is beyond `DAILY_LOSS_LIMIT_USDC`
- mainnet is selected without the subaccount guard and acknowledgement

## Hedge Mode Notes

`POSITION_MODE=hedge` makes Binance orders include `positionSide=LONG` or `positionSide=SHORT`.
Protective orders are per-trade quantity orders, not `closePosition=true`, so one TP/SL does not close the whole side.
Binance will not enable Hedge Mode while positions or open orders exist; use `position-mode set-hedge` only when the Demo account is flat.

BTCUSDC and BTCUSDT are independent symbols, so one One-way position in each symbol can coexist. This is not Hedge Mode: entries within the same symbol still merge into that symbol's single net position. BTCUSDT support here is intended for Demo/testnet; mainnet remains behind the existing subaccount and real-money guards.

Manual Demo orders normally require both stop-loss and take-profit. `open-manual --no-stop-loss` is an explicit Testnet-only exception: it keeps take-profit mandatory, records the omission in the ledger and notification, and does not relax the automatic engine or enable mainnet execution.

## Playbook

The operational rules live in [PLAYBOOK.md](PLAYBOOK.md). Update that document before enabling new setups or changing the active market regime.

## Intended First Playbook

Start with the narrow setup that looked strongest in the May backtest:

```text
Beecthor bearish regime
price enters resistance zone
rejection appears
short setup has >= 2R potential
stop is close enough
position size is tiny
```

Longs at support are allowed by the data model but should stay smaller and require stronger confirmation.
