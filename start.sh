#!/usr/bin/env bash
set -e
python collector.py --symbol "${SYMBOL:-BTC/USDT}" --interval "${POLL_INTERVAL:-5}" \
  --depth "${BOOK_DEPTH:-30}" --large-trade-usd "${LARGE_TRADE_USD:-100000}" &
COLLECTOR_PID=$!
python signal_engine.py --symbol "${SYMBOL:-BTC/USDT}" \
  --notional "${PAPER_NOTIONAL:-1000}" --fee-bps "${FEE_BPS_PER_SIDE:-10}" \
  --slippage-bps "${SLIPPAGE_BPS_PER_SIDE:-5}" --min-net-pnl "${MIN_NET_PNL:-0.10}" \
  --min-coverage "${MIN_BOOK_COVERAGE_PCT:-99}" --max-age "${MAX_SNAPSHOT_AGE_SECONDS:-15}" &
SIGNAL_PID=$!
cleanup() { kill "$COLLECTOR_PID" "$SIGNAL_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
streamlit run app.py --server.address 0.0.0.0 --server.port "${PORT:-8501}" --server.headless true
