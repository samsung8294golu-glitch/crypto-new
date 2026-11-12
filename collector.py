import argparse, csv, os, time
from datetime import datetime, timezone
import ccxt

EXCHANGES = ["binance", "coinbase", "bybit", "okx"]
FIELDS_BOOK = ["received_utc","exchange","symbol","exchange_timestamp_ms","best_bid","best_ask","mid","spread_bps","bid_depth_quote","ask_depth_quote","depth_imbalance","bid_levels","ask_levels"]
FIELDS_LEVELS = ["received_utc","exchange","symbol","side","price","amount","quote_value"]
FIELDS_TRADES = ["received_utc","exchange","symbol","trade_timestamp_ms","trade_id","side","price","amount","quote_value","large_trade_threshold_quote","is_large_trade"]

def make_exchange(name):
    ex = getattr(ccxt, name)({"enableRateLimit": True, "timeout": 20000})
    ex.load_markets()
    return ex

def resolve_symbol(ex, preferred):
    # Cross-exchange comparisons must use the same quote asset.
    # Do not silently substitute BTC/USD or BTC/USDC for BTC/USDT.
    return preferred if preferred in ex.markets else None

def depth_quote(levels, mid, band_bps):
    lo, hi = mid*(1-band_bps/10000), mid*(1+band_bps/10000)
    return sum(float(p)*float(q) for p,q in levels if lo <= float(p) <= hi)

def append_rows(path, fields, rows):
    exists = os.path.exists(path) and os.path.getsize(path)>0
    with open(path,"a",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        if not exists: w.writeheader()
        w.writerows(rows); f.flush()

def main():
    p=argparse.ArgumentParser(description="V4 public market-data collector; research only.")
    p.add_argument("--symbol",choices=["BTC/USDT","ETH/USDT"],default="BTC/USDT")
    p.add_argument("--interval",type=float,default=5)
    p.add_argument("--depth",type=int,default=30)
    p.add_argument("--band-bps",type=float,default=30)
    p.add_argument("--large-trade-usd",type=float,default=100000)
    p.add_argument("--book-file",default="orderbook_data.csv")
    p.add_argument("--levels-file",default="book_levels.csv")
    p.add_argument("--trades-file",default="trades_data.csv")
    a=p.parse_args()
    exchanges={}
    for name in EXCHANGES:
        try:
            ex=make_exchange(name); sym=resolve_symbol(ex,a.symbol)
            if sym: exchanges[name]=(ex,sym); print("[READY]",name,sym)
            else: print("[SKIP] no compatible symbol:",name)
        except Exception as e: print("[INIT ERROR]",name,str(e)[:140])
    if len(exchanges)<2: raise SystemExit("At least two exchanges are required.")
    print("V4 collector running. Ctrl+C to stop. Public data only.")
    try:
        while True:
            started=time.monotonic()
            for name,(ex,sym) in exchanges.items():
                now=datetime.now(timezone.utc).isoformat()
                try:
                    book=ex.fetch_order_book(sym,limit=max(10,min(100,a.depth)))
                    bids,asks=book.get("bids",[]),book.get("asks",[])
                    if bids and asks:
                        bid,ask=float(bids[0][0]),float(asks[0][0]); mid=(bid+ask)/2
                        bq=depth_quote(bids,mid,a.band_bps); aq=depth_quote(asks,mid,a.band_bps)
                        total=bq+aq
                        append_rows(a.book_file,FIELDS_BOOK,[{
                            "received_utc":now,"exchange":name,"symbol":sym,"exchange_timestamp_ms":book.get("timestamp"),
                            "best_bid":bid,"best_ask":ask,"mid":mid,"spread_bps":(ask-bid)/mid*10000,
                            "bid_depth_quote":bq,"ask_depth_quote":aq,"depth_imbalance":(bq-aq)/total if total else 0,
                            "bid_levels":len(bids),"ask_levels":len(asks)}])
                        level_rows=[]
                        for side,levels in (("bid",bids),("ask",asks)):
                            for price,amount in levels:
                                level_rows.append({"received_utc":now,"exchange":name,"symbol":sym,"side":side,
                                                   "price":float(price),"amount":float(amount),"quote_value":float(price)*float(amount)})
                        append_rows(a.levels_file,FIELDS_LEVELS,level_rows)
                    try:
                        trades=ex.fetch_trades(sym,limit=100)
                        trade_rows=[]
                        for t in trades:
                            price=float(t.get("price") or 0); amount=float(t.get("amount") or 0)
                            value=price*amount
                            trade_rows.append({"received_utc":now,"exchange":name,"symbol":sym,
                                "trade_timestamp_ms":t.get("timestamp"),"trade_id":t.get("id"),"side":t.get("side"),
                                "price":price,"amount":amount,"quote_value":value,
                                "large_trade_threshold_quote":a.large_trade_usd,"is_large_trade":value>=a.large_trade_usd})
                        if trade_rows: append_rows(a.trades_file,FIELDS_TRADES,trade_rows)
                        large=sum(1 for r in trade_rows if r["is_large_trade"])
                        print(f"{name:8s} mid={mid:.2f} trades={len(trade_rows)} large={large}")
                    except Exception as e: print("[TRADES ERROR]",name,str(e)[:100])
                except Exception as e: print("[BOOK ERROR]",name,str(e)[:120])
            time.sleep(max(0,a.interval-(time.monotonic()-started)))
    except KeyboardInterrupt: print("Stopped; CSV data saved.")

if __name__=="__main__": main()
