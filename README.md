# Crypto Blind-Spot AI V4

## What V4 adds
1. **Large public trade activity:** collects exchange trade prints and flags trades above a configurable quote-value threshold. This is not on-chain whale-wallet identification.
2. **Large displayed order tracking:** saves order-book price levels and estimates persistence when a large price level is repeatedly observed. It cannot identify an individual order across snapshots.
3. **Liquidity heatmap:** plots sampled displayed liquidity by time and price bucket.
4. **Exploratory lead–lag analysis:** compares returns at configurable snapshot offsets. This is research only, not a validated predictive AI model.
5. **Optional Telegram test alert:** uses environment secrets; never put bot tokens in source code or public repositories.

## Run
Requires Python 3.10+ and a persistent Python host:
```bash
pip install -r requirements.txt
python collector.py --symbol BTC/USDT --interval 5 --depth 30 --large-trade-usd 100000
streamlit run app.py
```
For ETH, run a separate collector process with separate output filenames:
```bash
python collector.py --symbol ETH/USDT --interval 5 --depth 30 --book-file eth_orderbook.csv --levels-file eth_levels.csv --trades-file eth_trades.csv
```
Enter the corresponding CSV paths in the dashboard.

## Telegram
Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as secrets/environment variables in your hosting provider. The dashboard's test button sends a test message. Do not share the token in chat or commit it to GitHub.

## iPhone-only note
The ZIP does not run directly as a native iPhone app. It must be uploaded to a hosted Python environment that supports a persistent collector process plus Streamlit. Free hosts may sleep or stop background processes. A mobile browser can open the hosted dashboard once deployed.

## Important limits
- REST polling is sequential and not synchronized. It cannot establish millisecond-level arbitrage.
- Large trade prints do not identify the trader or wallet; they are not proof of whale accumulation.
- Displayed orders can be cancelled, modified, filled, or move outside the sampled range.
- The heatmap is based on sampled snapshots, not a full exchange event stream.
- Lead–lag correlation is exploratory, not machine-learning prediction and not proof of an exploitable edge.
- No trade execution, no guaranteed profit, and no investment advice. Validate on out-of-sample data and include fees, spread, slippage, latency, partial fills and inventory risk before considering any strategy.

## Simplest hosted run (single service)
The package includes `start.sh` and `Procfile` for a single persistent service. The script starts the collector and the Streamlit dashboard in the same container, so they can read/write the same CSV files.

1. Extract this ZIP on your phone.
2. Create a GitHub repository and upload the contents of the `crypto_blindspot_ai_v4` folder (not the enclosing folder itself).
3. In Railway, create a project and deploy the GitHub repository as a service.
4. Set the service start command to `bash start.sh` if Railway does not automatically use the Procfile.
5. In Railway networking settings, generate a public domain. Open that URL in Safari.
6. The first market defaults to BTC/USDT. To change it, set the `SYMBOL` variable to `ETH/USDT` and redeploy.

This is a persistent cloud service and may incur hosting charges depending on the provider's current plan and usage. Configure a persistent volume only if you want collected CSV history to survive container replacement/redeploy; mount it at the project working directory and ensure the service writes its CSV files there.

## V4.1 automatic signal engine (paper/alert only)
`signal_engine.py` scans latest sampled top-of-book quotes across exchanges. It estimates gross spread and subtracts configurable two-sided fee and slippage allowances. A candidate is written to `signals.csv` only when estimated net edge and displayed depth pass thresholds. `start.sh` starts the collector, signal engine, and dashboard together.

Environment settings:
- `FEE_BPS_PER_SIDE` (default 10)
- `SLIPPAGE_BPS_PER_SIDE` (default 5)
- `MIN_NET_EDGE_BPS` (default 15)
- `MIN_DEPTH_QUOTE` (default 50000)

The dashboard also calculates current candidates using editable assumptions. These are NOT verified executable arbitrage and are NOT buy/sell instructions. The engine places no exchange orders. No automatic live trading is included; that would require a separately designed, security-reviewed execution system and explicit risk controls.

## V4.2 conservative paper signal calculation
The signal engine now:
- Compares only the exact same requested market symbol/quote asset across exchanges (e.g. BTC/USDT with BTC/USDT; it will not silently compare BTC/USD with BTC/USDT).
- Rejects snapshots older than the configured age limit.
- Uses sampled order-book levels to estimate VWAP for a target quote-currency notional and matches the executable base quantity on both sides.
- Subtracts configurable fees on both sides and an extra slippage allowance.
- Requires a minimum book-coverage percentage and minimum estimated net P&L.
- Writes paper candidates to `signals.csv`; it never sends orders.

Default settings are conservative examples, not verified exchange fee schedules. Confirm each venue's actual fees and quote-currency conversion before interpreting results. Sequential REST snapshots remain unsynchronized and can become stale between observation and execution.


## V4.3 additions — explainable decision panel + virtual execution
- Adds a transparent rule-based BUY/SELL screening score: freshness (40%), order-book coverage (35%), estimated net return (25%).
- Shows the buy exchange, sell exchange, matched quantity, estimated P&L and the score rationale.
- Adds configurable virtual quote/base balances for each exchange.
- Simulates both legs only when virtual balances/inventory are sufficient, the score is at least 70/100, and estimated net P&L is positive.
- Keeps a session-level paper execution history and virtual wallet view.
- **No real trading:** no API keys, no exchange account connection, no order placement. This is not a trained ML model and does not predict or guarantee profit.


## V4.4 — automatic paper BUY/SELL
- Automatically simulates both virtual legs when the best candidate passes the configured filters, score threshold, positive estimated net P&L and virtual inventory checks.
- Includes a configurable cooldown per symbol and exchange route to reduce repeated simulations on Streamlit reruns.
- The mode is paper-only: no API keys, no account connection and no real exchange orders.
- This is rule-based screening, not a trained AI model. Automatic paper fills are estimates and do not represent real executable fills.


## V4.4.2 bug-fix release
- Imports Python `time`, required by the automatic paper-trading cooldown timer.
- Initializes the per-route cooldown dictionary in Streamlit session state before it is read.
- Reset action now clears virtual wallets, paper-trade history, and cooldown timestamps together.
- Python syntax/AST checks pass for the dashboard; collector and signal engine syntax checks pass.
- This is a code-level fix only. It does not establish successful Railway deployment or profitable live-market behavior.
