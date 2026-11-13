import argparse
import csv
import os
import time
from datetime import datetime, timezone

import ccxt


EXCHANGES = ["binance", "coinbase", "bybit", "okx"]

FIELDS_BOOK = [
    "received_utc", "exchange", "symbol", "exchange_timestamp_ms",
    "best_bid", "best_ask", "mid", "spread_bps",
    "bid_depth_quote", "ask_depth_quote", "depth_imbalance",
    "bid_levels", "ask_levels",
]
FIELDS_LEVELS = [
    "received_utc", "exchange", "symbol", "side",
    "price", "amount", "quote_value",
]
FIELDS_TRADES = [
    "received_utc", "exchange", "symbol", "trade_timestamp_ms",
    "trade_id", "side", "price", "amount", "quote_value",
    "large_trade_threshold_quote", "is_large_trade",
]


def make_exchange(name):
    exchange_class = getattr(ccxt, name)
    exchange = exchange_class({"enableRateLimit": True, "timeout": 20000})
    exchange.load_markets()
    return exchange


def resolve_symbol(exchange, preferred):
    # Compare only the same quote asset; never silently substitute a market.
    return preferred if preferred in exchange.markets else None


def parse_book_level(level):
    """Read price and amount from a CCXT order-book level.

    Some exchanges (including OKX) return extra fields such as order count.
    Only the first two fields are needed here.
    """
    if not isinstance(level, (list, tuple)) or len(level) < 2:
        return None
    try:
        price = float(level[0])
        amount = float(level[1])
    except (TypeError, ValueError, OverflowError):
        return None
    if price <= 0 or amount < 0:
        return None
    return price, amount


def depth_quote(levels, mid, band_bps):
    lo = mid * (1 - band_bps / 10000)
    hi = mid * (1 + band_bps / 10000)
    total = 0.0
    for raw_level in levels:
        parsed = parse_book_level(raw_level)
        if parsed is None:
            continue
        price, amount = parsed
        if lo <= price <= hi:
            total += price * amount
    return total


def append_rows(path, fields, rows):
    if not rows:
        return
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)
        file_handle.flush()


def main():
    parser = argparse.ArgumentParser(
        description="V4 public market-data collector; research only."
    )
    parser.add_argument(
        "--symbol", choices=["BTC/USDT", "ETH/USDT"], default="BTC/USDT"
    )
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--depth", type=int, default=30)
    parser.add_argument("--band-bps", type=float, default=30)
    parser.add_argument("--large-trade-usd", type=float, default=100000)
    parser.add_argument("--book-file", default="orderbook_data.csv")
    parser.add_argument("--levels-file", default="book_levels.csv")
    parser.add_argument("--trades-file", default="trades_data.csv")
    args = parser.parse_args()

    exchanges = {}
    for name in EXCHANGES:
        try:
            exchange = make_exchange(name)
            symbol = resolve_symbol(exchange, args.symbol)
            if symbol:
                exchanges[name] = (exchange, symbol)
                print("[READY]", name, symbol, flush=True)
            else:
                print("[SKIP] no compatible symbol:", name, args.symbol, flush=True)
        except Exception as exc:
            print("[INIT ERROR]", name, str(exc)[:140], flush=True)

    if len(exchanges) < 2:
        raise SystemExit("At least two exchanges are required for comparison.")

    print("V4 collector running. Ctrl+C to stop. Public data only.", flush=True)

    try:
        while True:
            cycle_started = time.monotonic()

            for name, (exchange, symbol) in exchanges.items():
                received_utc = datetime.now(timezone.utc).isoformat()
                mid = None

                try:
                    book = exchange.fetch_order_book(
                        symbol, limit=max(10, min(100, args.depth))
                    )
                    bids = book.get("bids") or []
                    asks = book.get("asks") or []

                    valid_bids = [
                        parsed for parsed in (parse_book_level(x) for x in bids)
                        if parsed is not None
                    ]
                    valid_asks = [
                        parsed for parsed in (parse_book_level(x) for x in asks)
                        if parsed is not None
                    ]

                    if valid_bids and valid_asks:
                        bid = valid_bids[0][0]
                        ask = valid_asks[0][0]
                        mid = (bid + ask) / 2.0

                        bid_depth = depth_quote(bids, mid, args.band_bps)
                        ask_depth = depth_quote(asks, mid, args.band_bps)
                        total_depth = bid_depth + ask_depth

                        append_rows(
                            args.book_file,
                            FIELDS_BOOK,
                            [{
                                "received_utc": received_utc,
                                "exchange": name,
                                "symbol": symbol,
                                "exchange_timestamp_ms": book.get("timestamp"),
                                "best_bid": bid,
                                "best_ask": ask,
                                "mid": mid,
                                "spread_bps": (ask - bid) / mid * 10000,
                                "bid_depth_quote": bid_depth,
                                "ask_depth_quote": ask_depth,
                                "depth_imbalance": (
                                    (bid_depth - ask_depth) / total_depth
                                    if total_depth else 0
                                ),
                                "bid_levels": len(valid_bids),
                                "ask_levels": len(valid_asks),
                            }],
                        )

                        level_rows = []
                        for side, raw_levels in (("bid", bids), ("ask", asks)):
                            for raw_level in raw_levels:
                                parsed = parse_book_level(raw_level)
                                if parsed is None:
                                    continue
                                price, amount = parsed
                                level_rows.append({
                                    "received_utc": received_utc,
                                    "exchange": name,
                                    "symbol": symbol,
                                    "side": side,
                                    "price": price,
                                    "amount": amount,
                                    "quote_value": price * amount,
                                })
                        append_rows(args.levels_file, FIELDS_LEVELS, level_rows)
                    else:
                        print("[BOOK WARNING]", name, "empty/invalid bid or ask side", flush=True)

                except Exception as exc:
                    print("[BOOK ERROR]", name, str(exc)[:160], flush=True)

                try:
                    trades = exchange.fetch_trades(symbol, limit=100)
                    trade_rows = []

                    for trade in trades:
                        try:
                            price = float(trade.get("price") or 0)
                            amount = float(trade.get("amount") or 0)
                        except (TypeError, ValueError, OverflowError):
                            continue
                        if price <= 0 or amount < 0:
                            continue

                        quote_value = price * amount
                        trade_rows.append({
                            "received_utc": received_utc,
                            "exchange": name,
                            "symbol": symbol,
                            "trade_timestamp_ms": trade.get("timestamp"),
                            "trade_id": trade.get("id"),
                            "side": trade.get("side"),
                            "price": price,
                            "amount": amount,
                            "quote_value": quote_value,
                            "large_trade_threshold_quote": args.large_trade_usd,
                            "is_large_trade": quote_value >= args.large_trade_usd,
                        })

                    append_rows(args.trades_file, FIELDS_TRADES, trade_rows)
                    large_count = sum(1 for row in trade_rows if row["is_large_trade"])
                    if mid is not None:
                        print(
                            f"{name:8s} mid={mid:.2f} "
                            f"trades={len(trade_rows)} large={large_count}",
                            flush=True,
                        )
                    else:
                        print(
                            f"{name:8s} mid=unavailable "
                            f"trades={len(trade_rows)} large={large_count}",
                            flush=True,
                        )
                except Exception as exc:
                    print("[TRADES ERROR]", name, str(exc)[:160], flush=True)

            sleep_seconds = max(0.0, args.interval - (time.monotonic() - cycle_started))
            time.sleep(sleep_seconds)

    except KeyboardInterrupt:
        print("Stopped; CSV data saved.", flush=True)


if __name__ == "__main__":
    main()
