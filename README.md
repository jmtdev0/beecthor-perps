# Beecthor Perps

Dedicated automation workspace for testing Beecthor-derived BTCUSDT perpetual futures strategies.

The repo is intentionally conservative:

- `shadow` mode is the default and never sends exchange orders.
- `testnet` must be explicit.
- `mainnet` is blocked unless a dedicated subaccount and real-money acknowledgement are configured.
- Strategy output is an order intent, not an order, until it passes deterministic safety checks.
- BTCUSDT order size starts at the practical minimum of `0.001 BTC`; keep `MAX_NOTIONAL_USDT` aligned with current BTC price.

## Quick Start

```powershell
cd E:\Software\Coding\beecthor-perps
$env:PYTHONPATH="$PWD\src"
python -m unittest
python -m beecthor_perps status
python -m beecthor_perps evaluate --thesis examples\beecthor_thesis.sample.json --price 78100
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

## Safety Contract

The bot must refuse to trade when any of these are true:

- symbol is outside `SYMBOL_ALLOWLIST`
- notional is above `MAX_NOTIONAL_USDT`
- leverage is above `MAX_LEVERAGE`
- stop loss or take profit is missing
- stop/take-profit direction is invalid
- there is already an open position beyond `MAX_OPEN_POSITIONS`
- daily realized loss is beyond `DAILY_LOSS_LIMIT_USDT`
- mainnet is selected without the subaccount guard and acknowledgement

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
