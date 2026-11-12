import argparse, csv, os, time
from datetime import datetime, timezone
import pandas as pd

FIELDS=["created_utc","symbol","quote_asset","buy_exchange","sell_exchange","target_quote_notional",
"filled_buy_base","filled_sell_base","buy_vwap","sell_vwap","gross_pnl_quote","buy_fee_quote",
"sell_fee_quote","slippage_allowance_quote","estimated_net_pnl_quote","estimated_net_return_pct",
"buy_book_coverage_pct","sell_book_coverage_pct","snapshot_age_seconds","status","note"]

def consume(levels, side, target_quote):
    # Walk asks from cheapest to most expensive for buys; bids highest to lowest for sells.
    rows=levels[levels.side==side].copy()
    rows["price"]=pd.to_numeric(rows.price,errors="coerce")
    rows["amount"]=pd.to_numeric(rows.amount,errors="coerce")
    rows=rows.dropna(subset=["price","amount"])
    rows=rows.sort_values("price",ascending=(side=="ask"))
    remaining=target_quote; base=0.0; quote=0.0
    for r in rows.itertuples():
        p=float(r.price); qty=float(r.amount)
        if p<=0 or qty<=0: continue
        take=min(qty,remaining/p)
        base+=take; spent=take*p; quote+=spent; remaining-=spent
        if remaining<=1e-9: break
    coverage=(quote/target_quote*100) if target_quote>0 else 0
    vwap=(quote/base) if base>0 else None
    return base,quote,vwap,coverage

def main():
    p=argparse.ArgumentParser(description="V4.2 conservative paper arbitrage candidate engine")
    p.add_argument("--symbol",default="BTC/USDT")
    p.add_argument("--books",default="orderbook_data.csv")
    p.add_argument("--levels",default="book_levels.csv")
    p.add_argument("--output",default="signals.csv")
    p.add_argument("--notional",type=float,default=1000,help="target quote-currency notional per side")
    p.add_argument("--fee-bps",type=float,default=10,help="fee per side")
    p.add_argument("--slippage-bps",type=float,default=5,help="extra slippage allowance per side")
    p.add_argument("--min-net-pnl",type=float,default=0.10)
    p.add_argument("--min-coverage",type=float,default=99)
    p.add_argument("--max-age",type=float,default=15)
    p.add_argument("--interval",type=float,default=5)
    p.add_argument("--cooldown",type=int,default=60)
    a=p.parse_args()
    last_key=None; last_emit=0
    print("V4.2 PAPER SIGNAL ENGINE ONLY — no exchange orders are sent.")
    while True:
        try:
            if os.path.exists(a.books) and os.path.exists(a.levels):
                books=pd.read_csv(a.books); levels=pd.read_csv(a.levels)
                books=books[books.symbol==a.symbol].copy()
                levels=levels[levels.symbol==a.symbol].copy()
                if not books.empty and not levels.empty:
                    books["received_utc"]=pd.to_datetime(books.received_utc,utc=True,errors="coerce")
                    levels["received_utc"]=pd.to_datetime(levels.received_utc,utc=True,errors="coerce")
                    now=pd.Timestamp.now(tz="UTC")
                    latest=books.dropna(subset=["received_utc"]).sort_values("received_utc").groupby("exchange").tail(1)
                    candidates=[]
                    for buy in latest.to_dict("records"):
                        for sell in latest.to_dict("records"):
                            if buy["exchange"]==sell["exchange"]: continue
                            # Strict same quote asset guard.
                            buy_quote=str(buy["symbol"]).split("/")[-1]
                            sell_quote=str(sell["symbol"]).split("/")[-1]
                            if buy_quote!=sell_quote: continue
                            age_buy=(now-buy["received_utc"]).total_seconds()
                            age_sell=(now-sell["received_utc"]).total_seconds()
                            age=max(age_buy,age_sell)
                            if age<0 or age>a.max_age: continue
                            buy_lv=levels[(levels.exchange==buy["exchange"]) & (levels.received_utc==buy["received_utc"])]
                            sell_lv=levels[(levels.exchange==sell["exchange"]) & (levels.received_utc==sell["received_utc"])]
                            bqty,bquote,bvwap,bcov=consume(buy_lv,"ask",a.notional)
                            sqty,squote,svwap,scov=consume(sell_lv,"bid",a.notional)
                            if bvwap is None or svwap is None or min(bcov,scov)<a.min_coverage: continue
                            qty=min(bqty,sqty)
                            if qty<=0: continue
                            # Recompute matched-size VWAP at equal base quantity, using top levels again.
                            def consume_base(df,side,target_base):
                                r=df[df.side==side].copy()
                                r["price"]=pd.to_numeric(r.price,errors="coerce"); r["amount"]=pd.to_numeric(r.amount,errors="coerce")
                                r=r.dropna(subset=["price","amount"]).sort_values("price",ascending=(side=="ask"))
                                left=target_base; q=0; b=0
                                for x in r.itertuples():
                                    take=min(float(x.amount),left); q+=take*float(x.price); b+=take; left-=take
                                    if left<=1e-12: break
                                return (q/b if b else None),q
                            buy_vwap,buy_quote=consume_base(buy_lv,"ask",qty)
                            sell_vwap,sell_quote=consume_base(sell_lv,"bid",qty)
                            if not buy_vwap or not sell_vwap: continue
                            gross=sell_quote-buy_quote
                            buy_fee=buy_quote*a.fee_bps/10000
                            sell_fee=sell_quote*a.fee_bps/10000
                            slip=(buy_quote+sell_quote)*a.slippage_bps/10000
                            net=gross-buy_fee-sell_fee-slip
                            if net>=a.min_net_pnl:
                                candidates.append({"created_utc":datetime.now(timezone.utc).isoformat(),
                                    "symbol":a.symbol,"quote_asset":str(buy["symbol"]).split("/")[-1],
                                    "buy_exchange":buy["exchange"],"sell_exchange":sell["exchange"],
                                    "target_quote_notional":a.notional,"filled_buy_base":qty,"filled_sell_base":qty,
                                    "buy_vwap":buy_vwap,"sell_vwap":sell_vwap,"gross_pnl_quote":gross,
                                    "buy_fee_quote":buy_fee,"sell_fee_quote":sell_fee,
                                    "slippage_allowance_quote":slip,"estimated_net_pnl_quote":net,
                                    "estimated_net_return_pct":net/buy_quote*100 if buy_quote else 0,
                                    "buy_book_coverage_pct":bcov,"sell_book_coverage_pct":scov,
                                    "snapshot_age_seconds":age,"status":"PAPER CANDIDATE",
                                    "note":"Same quote asset; sampled depth VWAP; fees/slippage are estimates; no order execution."})
                    if candidates:
                        best=max(candidates,key=lambda x:x["estimated_net_pnl_quote"])
                        key=(best["buy_exchange"],best["sell_exchange"],round(best["estimated_net_pnl_quote"],6))
                        now_s=time.time()
                        if key!=last_key or now_s-last_emit>=a.cooldown:
                            exists=os.path.exists(a.output) and os.path.getsize(a.output)>0
                            with open(a.output,"a",newline="",encoding="utf-8") as f:
                                w=csv.DictWriter(f,fieldnames=FIELDS)
                                if not exists: w.writeheader()
                                w.writerow(best)
                            print("[PAPER CANDIDATE]",best["buy_exchange"],"->",best["sell_exchange"],
                                  "estimated net",round(best["estimated_net_pnl_quote"],4),best["quote_asset"])
                            last_key=key; last_emit=now_s
        except Exception as e:
            print("[ENGINE ERROR]",str(e)[:200])
        time.sleep(max(1,a.interval))

if __name__=="__main__": main()
