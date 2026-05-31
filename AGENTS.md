# AGENTS.md

## Purpose

This repository automates a cautious Beecthor-to-perpetual-futures workflow for Binance USD-M Futures.

The system must prefer shadow decisions and testnet execution before any real-money path. Mainnet automation is considered dangerous by default.

## Working Rules

1. Keep code, comments, identifiers, and docs in English unless the user asks for Spanish-facing text.
2. Never commit secrets, API keys, account identifiers, or raw private trading logs.
3. Default to `PERPS_ENV=shadow`. Testnet must be explicit. Mainnet must be double-confirmed.
4. Do not add wallet, withdrawal, transfer, earn, spot, or margin trading capabilities unless explicitly requested and reviewed.
5. All entry trades must pass safety validation: symbol allowlist, notional cap, leverage cap, stop loss, take profit, and stale-data checks.
6. Mainnet must require a dedicated subaccount, IP-restricted API keys, isolated futures, and hard-coded local limits.
7. Closing/risk-reducing orders should use reduce-only or close-position semantics whenever the exchange supports them.
8. Preserve logs and decision ledgers; they are required for audit, tax, and post-trade analysis.

## Operating Principles

- The LLM can summarize and audit a thesis, but deterministic rules own sizing, leverage, order placement, and kill-switch behavior.
- The first production playbook should be narrow: BTCUSDT short at resistance inside a bearish Beecthor regime.
- If a decision is ambiguous, stale, over-sized, or missing risk levels, the correct action is `WAIT`.
