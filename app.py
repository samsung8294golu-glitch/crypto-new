import os
import time
import pandas as pd
import streamlit as st
import plotly.express as px
import requests
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Crypto Blind-Spot AI V4.4",page_icon="🔎",layout="wide")
st_autorefresh(interval=5000, key="crypto_blindspot_auto_refresh_v44")
st.title("🔎 Crypto Blind-Spot AI — V4.4")
st.caption("Market microstructure research dashboard • Explainable decision scoring • Virtual paper execution only")
st.warning("Research prototype. REST polling is sequential and asynchronous. Large public trades are not verified whale-wallet activity. Displayed orders may be cancelled or moved; no signal guarantees profit.")

book_path=st.text_input("Order-book snapshots CSV","orderbook_data.csv")
levels_path=st.text_input("Order-book levels CSV","book_levels.csv")
trades_path=st.text_input("Public trades CSV","trades_data.csv")
def load(path):
    if not os.path.exists(path): return pd.DataFrame()
    try: return pd.read_csv(path)
    except Exception as e:
        st.error(f"Cannot read {path}: {e}"); return pd.DataFrame()
book,levels,trades=load(book_path),load(levels_path),load(trades_path)
if book.empty:
    st.info("No data yet. Start collector.py using the README instructions, then refresh this dashboard.")
    st.stop()
for col in ["received_utc"]:
    book[col]=pd.to_datetime(book[col],utc=True,errors="coerce")
for col in ["mid","best_bid","best_ask","spread_bps","bid_depth_quote","ask_depth_quote","depth_imbalance"]:
    book[col]=pd.to_numeric(book[col],errors="coerce")
book=book.dropna(subset=["received_utc","mid"]).sort_values("received_utc")
symbols=sorted(book.symbol.dropna().unique())
symbol=st.selectbox("Market",symbols)
d=book[book.symbol==symbol].copy()
latest=d.groupby("exchange").tail(1)
c1,c2,c3=st.columns(3)
c1.metric("Order-book snapshots",f"{len(d):,}")
c2.metric("Exchanges",str(d.exchange.nunique()))
c3.metric("Latest sample (UTC)",str(d.received_utc.max()))
st.subheader("1. Live-ish order-book overview")
st.dataframe(latest[["exchange","received_utc","best_bid","best_ask","spread_bps","bid_depth_quote","ask_depth_quote","depth_imbalance"]],use_container_width=True)
st.subheader("2. Liquidity depth and imbalance")
p=d.pivot_table(index="received_utc",columns="exchange",values=["bid_depth_quote","ask_depth_quote"],aggfunc="last").sort_index()
st.plotly_chart(px.line(p.reset_index(),x="received_utc",y=[c for c in p.columns],title="Bid / ask depth (quote currency)"),use_container_width=True)
q=d.pivot_table(index="received_utc",columns="exchange",values="depth_imbalance",aggfunc="last").sort_index()
st.plotly_chart(px.line(q.reset_index(),x="received_utc",y=list(q.columns),title="Order-book imbalance"),use_container_width=True)
st.caption("Imbalance = (bid depth − ask depth) / (bid depth + ask depth).")

st.subheader("3. Large public trade activity")
threshold=st.number_input("Large-trade threshold (quote currency)",min_value=1000.0,value=100000.0,step=10000.0)
if not trades.empty:
    trades=trades.copy()
    trades["quote_value"]=pd.to_numeric(trades.quote_value,errors="coerce")
    td=trades[trades.symbol==symbol].copy()
    td["received_utc"]=pd.to_datetime(td.received_utc,utc=True,errors="coerce")
    large=td[td.quote_value>=threshold].sort_values("received_utc",ascending=False)
    st.metric("Trades above threshold",f"{len(large):,}")
    if not large.empty: st.dataframe(large[["received_utc","exchange","side","price","amount","quote_value"]].head(100),use_container_width=True)
    else: st.info("No trades exceed this threshold in the collected data.")
    if not td.empty:
        flow=td.groupby(["exchange","side"],dropna=False).quote_value.sum().reset_index()
        st.plotly_chart(px.bar(flow,x="exchange",y="quote_value",color="side",barmode="group",title="Observed public trade value by side"),use_container_width=True)
else: st.info("Trade file not found yet. Collector creates trades_data.csv.")

st.subheader("4. Large order persistence tracker")
if not levels.empty:
    lv=levels[levels.symbol==symbol].copy()
    lv["received_utc"]=pd.to_datetime(lv.received_utc,utc=True,errors="coerce")
    lv["quote_value"]=pd.to_numeric(lv.quote_value,errors="coerce")
    min_order=st.number_input("Displayed order size threshold (quote currency)",min_value=1000.0,value=250000.0,step=25000.0)
    big=lv[lv.quote_value>=min_order]
    if not big.empty:
        persistence=big.groupby(["exchange","side","price"]).agg(observations=("received_utc","nunique"),first_seen=("received_utc","min"),last_seen=("received_utc","max"),max_quote=("quote_value","max")).reset_index()
        persistence=persistence.sort_values(["observations","max_quote"],ascending=False)
        st.dataframe(persistence.head(100),use_container_width=True)
        st.caption("Repeated price-level observations suggest persistence only; REST snapshots cannot prove the same individual order remained live.")
    else: st.info("No price level exceeds the selected size threshold.")
else: st.info("Level file not found yet. Collector creates book_levels.csv.")

st.subheader("5. Liquidity heatmap")
if not levels.empty:
    lv=levels[levels.symbol==symbol].copy()
    lv["received_utc"]=pd.to_datetime(lv.received_utc,utc=True,errors="coerce")
    lv["quote_value"]=pd.to_numeric(lv.quote_value,errors="coerce")
    if not lv.empty:
        lv["price_bucket"]=lv.price.astype(float).round(-1 if symbol.startswith("BTC") else 0)
        heat=lv.groupby(["received_utc","price_bucket"]).quote_value.sum().reset_index()
        st.plotly_chart(px.density_heatmap(heat,x="received_utc",y="price_bucket",z="quote_value",histfunc="sum",title="Observed displayed liquidity by time and price bucket"),use_container_width=True)
else: st.info("Collect order-book levels to populate the heatmap.")

st.subheader("6. Exploratory lead–lag analysis")
st.caption("This is a coarse exploratory correlation, not a predictive model. Uneven polling and unsynchronized clocks can bias results.")
if d.exchange.nunique()>=2:
    leader=st.selectbox("Reference exchange",sorted(d.exchange.unique()))
    lagger=st.selectbox("Comparison exchange",[x for x in sorted(d.exchange.unique()) if x!=leader])
    step=int(st.slider("Lag in snapshot steps",1,10,1))
    wide=d.pivot_table(index="received_utc",columns="exchange",values="mid",aggfunc="last").sort_index().ffill()
    if leader in wide and lagger in wide:
        ret=wide[[leader,lagger]].pct_change().dropna()
        corr=ret[leader].corr(ret[lagger].shift(-step))
        st.metric("Correlation at selected step offset",f"{corr:.3f}" if pd.notna(corr) else "Insufficient data")
        st.caption("Positive/negative offsets are exploratory only. Do not interpret correlation as a guaranteed lead or trade signal.")
st.subheader("7. Telegram alerts (optional)")
st.write("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as environment secrets on your hosting service. This dashboard does not expose or store credentials.")
if st.button("Send test Telegram alert"):
    token=os.getenv("TELEGRAM_BOT_TOKEN"); chat=os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat: st.error("Telegram secrets are not configured in the hosting environment.")
    else:
        try:
            r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",data={"chat_id":chat,"text":"Crypto Blind-Spot AI V4 test alert"},timeout=10)
            st.success("Telegram API response: "+str(r.status_code) if r.ok else "Telegram request failed: "+r.text[:200])
        except Exception as e: st.error(f"Telegram error: {e}")


st.subheader("8. Automatic cross-exchange signals (paper/alert only)")
st.caption("Conservative sampled order-book VWAP calculator. It compares only the exact same quote asset and rejects stale snapshots.")
notional=st.number_input("Paper trade size per side (quote currency)",min_value=10.0,value=1000.0,step=100.0)
fee_side=st.number_input("Estimated fee per side (bps)",min_value=0.0,value=10.0,step=1.0)
slip_side=st.number_input("Additional slippage allowance per side (bps)",min_value=0.0,value=5.0,step=1.0)
min_net=st.number_input("Minimum estimated net profit (quote currency)",min_value=0.0,value=0.10,step=0.10)
max_age=st.number_input("Maximum snapshot age (seconds)",min_value=1.0,value=15.0,step=1.0)
min_cov=st.slider("Minimum order-book coverage (%)",min_value=50,max_value=100,value=99)
signal_rows=[]
if not levels.empty:
    lv=levels[levels.symbol==symbol].copy()
    lv["received_utc"]=pd.to_datetime(lv.received_utc,utc=True,errors="coerce")
    now=pd.Timestamp.now(tz="UTC")
    for buy in latest.to_dict("records"):
        for sell in latest.to_dict("records"):
            if buy["exchange"]==sell["exchange"]: continue
            if str(buy["symbol"]).split("/")[-1] != str(sell["symbol"]).split("/")[-1]: continue
            buy_time=pd.to_datetime(buy["received_utc"],utc=True)
            sell_time=pd.to_datetime(sell["received_utc"],utc=True)
            age=max((now-buy_time).total_seconds(),(now-sell_time).total_seconds())
            if age<0 or age>max_age: continue
            bl=lv[(lv.exchange==buy["exchange"]) & (lv.received_utc==buy_time)]
            sl=lv[(lv.exchange==sell["exchange"]) & (lv.received_utc==sell_time)]
            def take_quote(frame,side,target):
                x=frame[frame.side==side].copy()
                x["price"]=pd.to_numeric(x.price,errors="coerce"); x["amount"]=pd.to_numeric(x.amount,errors="coerce")
                x=x.dropna(subset=["price","amount"]).sort_values("price",ascending=(side=="ask"))
                rem=target; qty=0.0; spent=0.0
                for r in x.itertuples():
                    amount=min(float(r.amount),rem/float(r.price))
                    qty+=amount; spent+=amount*float(r.price); rem-=amount*float(r.price)
                    if rem<=1e-8: break
                return qty,spent,spent/target*100 if target else 0
            bqty,bspent,bcov=take_quote(bl,"ask",notional)
            sqty,sspent,scov=take_quote(sl,"bid",notional)
            matched=min(bqty,sqty)
            if matched<=0 or min(bcov,scov)<min_cov: continue
            def take_base(frame,side,target):
                x=frame[frame.side==side].copy()
                x["price"]=pd.to_numeric(x.price,errors="coerce"); x["amount"]=pd.to_numeric(x.amount,errors="coerce")
                x=x.dropna(subset=["price","amount"]).sort_values("price",ascending=(side=="ask"))
                rem=target; spent=0.0; filled=0.0
                for r in x.itertuples():
                    amount=min(float(r.amount),rem); spent+=amount*float(r.price); filled+=amount; rem-=amount
                    if rem<=1e-12: break
                return spent, (spent/filled if filled else 0)
            bcost,bvwap=take_base(bl,"ask",matched); sproceeds,svwap=take_base(sl,"bid",matched)
            gross=sproceeds-bcost
            fees=(bcost+sproceeds)*fee_side/10000
            slip=(bcost+sproceeds)*slip_side/10000
            net=gross-fees-slip
            if net>=min_net:
                signal_rows.append({"Buy exchange":buy["exchange"],"Sell exchange":sell["exchange"],
                    "Matched quantity (base)":matched,"Buy VWAP":bvwap,"Sell VWAP":svwap,
                    "Gross P&L":gross,"Estimated fees":fees,"Slippage allowance":slip,
                    "Estimated net P&L":net,"Snapshot age (s)":round(age,1),
                    "Book coverage (buy/sell %)":f"{bcov:.1f}/{scov:.1f}","Status":"PAPER CANDIDATE"})
if signal_rows:
    signal_df=pd.DataFrame(signal_rows).sort_values("Estimated net P&L",ascending=False)
    st.dataframe(signal_df,use_container_width=True)
else:
    st.info("No candidate passed same-quote, freshness, depth-coverage and estimated-cost filters. No signal is a valid outcome.")
if os.path.exists("signals.csv"):
    hist=pd.read_csv("signals.csv")
    if not hist.empty:
        st.markdown("**Background signal history**")
        st.dataframe(hist.tail(50),use_container_width=True)
st.caption("Signal means a paper candidate only. It does not guarantee that two live orders can fill at these prices.")


st.subheader("9. Automatic BUY / SELL — paper trading")
st.info("AUTO PAPER MODE: Eligible signals can trigger virtual BUY and SELL legs automatically. This never sends real orders or uses exchange API keys.")
st.warning("SAFE MODE: This module simulates trades with virtual balances only. It does not connect to exchange accounts and cannot place real orders.")
st.caption("Explainable rule-based screening (not trained ML). Automatic simulation runs only when all filters, score, virtual balances and cooldown checks pass.")

# User-configurable virtual account balances, held separately for each exchange.
with st.expander("Paper wallet setup", expanded=True):
    p1, p2, p3 = st.columns(3)
    initial_quote = p1.number_input("Virtual quote balance per exchange", min_value=0.0, value=10000.0, step=500.0)
    initial_base = p2.number_input("Virtual BTC balance per exchange", min_value=0.0, value=0.10, step=0.01, format="%.5f")
    paper_fee_bps = p3.number_input("Paper fee per side (bps)", min_value=0.0, value=float(fee_side), step=1.0)
    auto_paper = st.checkbox("Automatically simulate eligible BUY + SELL signals", value=True)
    cooldown_seconds = st.number_input("Same pair/exchange route cooldown (seconds)", min_value=30, value=300, step=30)

if "paper_wallets_v44" not in st.session_state:
    st.session_state.paper_wallets_v44 = {}
if "paper_trades_v44" not in st.session_state:
    st.session_state.paper_trades_v44 = []
if "paper_last_route_time_v44" not in st.session_state:
    st.session_state.paper_last_route_time_v44 = {}

if signal_rows:
    ai_df = pd.DataFrame(signal_rows).sort_values("Estimated net P&L", ascending=False)
    best_ai = ai_df.iloc[0].to_dict()
    age_score = max(0.0, 1.0 - float(best_ai["Snapshot age (s)"]) / max(float(max_age), 1.0))
    coverage_score = min(1.0, min(float(x) for x in str(best_ai["Book coverage (buy/sell %)"]).split("/")) / 100.0)
    return_score = min(1.0, max(0.0, float(best_ai["Estimated net P&L"]) / max(float(notional) * 0.005, 0.01)))
    ai_score = round(100 * (0.40 * age_score + 0.35 * coverage_score + 0.25 * return_score))
    st.markdown("**Top explainable decision**")
    a1, a2, a3 = st.columns(3)
    a1.metric("Action", f"BUY {best_ai['Buy exchange']}")
    a2.metric("Opposite leg", f"SELL {best_ai['Sell exchange']}")
    a3.metric("Rule score", f"{ai_score}/100")
    st.write(f"Matched quantity: **{float(best_ai['Matched quantity (base)']):.8f} {symbol.split('/')[0]}** · Estimated net P&L: **{float(best_ai['Estimated net P&L']):.4f} {symbol.split('/')[-1]}**")
    st.caption("Score weights: snapshot freshness 40%, book coverage 35%, estimated net return 25%. It is a screening score, not a probability of profit.")
    if ai_score < 70:
        st.info("Decision: WATCH / SKIP. Score below 70; do not simulate unless you deliberately want to test a weaker setup.")
    else:
        st.success("Decision: PAPER-ELIGIBLE. Review balances and costs before running the virtual execution.")
    buy_ex = str(best_ai["Buy exchange"]); sell_ex = str(best_ai["Sell exchange"])
    quote_asset = symbol.split("/")[-1]
    base_asset = symbol.split("/")[0]
    for ex in sorted(set([buy_ex, sell_ex])):
        key = f"{symbol}|{ex}"
        if key not in st.session_state.paper_wallets_v44:
            st.session_state.paper_wallets_v44[key] = {"quote": float(initial_quote), "base": float(initial_base)}
    buy_wallet = st.session_state.paper_wallets_v44[f"{symbol}|{buy_ex}"]
    sell_wallet = st.session_state.paper_wallets_v44[f"{symbol}|{sell_ex}"]
    buy_cost = float(best_ai["Buy VWAP"]) * float(best_ai["Matched quantity (base)"])
    sell_value = float(best_ai["Sell VWAP"]) * float(best_ai["Matched quantity (base)"])
    buy_fee = buy_cost * float(paper_fee_bps) / 10000.0
    sell_fee = sell_value * float(paper_fee_bps) / 10000.0
    paper_slippage = float(best_ai["Slippage allowance"])
    paper_net = sell_value - sell_cost - buy_fee - sell_fee - paper_slippage
    st.markdown("**Pre-trade virtual balance check**")
    st.write(f"- {buy_ex}: {buy_wallet['quote']:.2f} {quote_asset} available; required approximately {buy_cost + buy_fee:.2f} {quote_asset}.")
    st.write(f"- {sell_ex}: {sell_wallet['base']:.8f} {base_asset} available; required {float(best_ai['Matched quantity (base)']):.8f} {base_asset}.")
    can_simulate = (buy_wallet["quote"] >= buy_cost + buy_fee and
                    sell_wallet["base"] >= float(best_ai["Matched quantity (base)"]) and
                    ai_score >= 70 and paper_net > 0)
    route_key = f"{symbol}|{buy_ex}|{sell_ex}"
    now_ts = time.time()
    last_ts = st.session_state.paper_last_route_time_v44.get(route_key, 0.0)
    cooldown_ok = (now_ts - last_ts) >= float(cooldown_seconds)
    auto_ready = bool(auto_paper and can_simulate and cooldown_ok)
    if auto_ready:
        qty = float(best_ai["Matched quantity (base)"])
        buy_wallet["quote"] -= buy_cost + buy_fee
        buy_wallet["base"] += qty
        sell_wallet["base"] -= qty
        sell_wallet["quote"] += sell_value - sell_fee
        trade = {"time_utc": pd.Timestamp.now(tz="UTC").isoformat(), "symbol": symbol,
                 "buy_exchange": buy_ex, "sell_exchange": sell_ex, "quantity": qty,
                 "buy_cost": buy_cost, "sell_value": sell_value, "fees": buy_fee + sell_fee,
                 "slippage_allowance": paper_slippage, "paper_net_pnl": paper_net,
                 "status": "AUTO PAPER SIMULATED — NOT REAL"}
        st.session_state.paper_trades_v44.append(trade)
        st.session_state.paper_last_route_time_v44[route_key] = now_ts
        st.success(f"Automatic virtual BUY on {buy_ex} and SELL on {sell_ex} simulated. Estimated P&L: {paper_net:.4f} {quote_asset}. No real order was sent.")
    elif auto_paper and can_simulate and not cooldown_ok:
        st.info(f"Automatic paper trade paused: this exchange route is in its {int(cooldown_seconds)}-second cooldown.")
    elif not can_simulate:
        st.info("Automatic paper trade blocked: insufficient virtual balance/inventory, score below 70, or estimated net P&L is not positive.")
    else:
        st.info("Automatic paper trading is OFF. Turn on the checkbox above to simulate eligible signals automatically.")
else:
    st.info("No eligible live-ish candidate at this moment. The AI-style panel will stay in WATCH mode until a candidate passes all filters.")

wallet_rows = []
for key, bal in st.session_state.paper_wallets_v44.items():
    pair, ex = key.split("|", 1)
    if pair == symbol:
        wallet_rows.append({"Exchange": ex, f"{quote_asset} balance": round(bal["quote"], 4), f"{base_asset} balance": round(bal["base"], 8)})
if wallet_rows:
    st.markdown("**Virtual balances after paper trades**")
    st.dataframe(pd.DataFrame(wallet_rows), use_container_width=True)
if st.session_state.paper_trades_v44:
    st.markdown("**Paper execution history**")
    st.dataframe(pd.DataFrame(st.session_state.paper_trades_v44).tail(50), use_container_width=True)
    if st.button("Reset paper wallets and history"):
        st.session_state.paper_wallets_v44 = {}
        st.session_state.paper_trades_v44 = []
        st.session_state.paper_last_route_time_v44 = {}
        st.rerun()
else:
    st.caption("No virtual trades simulated yet.")

st.subheader("Limitations")
st.markdown("""
- Public trade prints are exchange-level trades, not identified whale wallets or on-chain transfers.
- Large trade threshold is user-configured and must be adapted to market liquidity.
- Order-level persistence is inferred from repeated price levels; individual order identity is unavailable from these snapshots.
- Heatmap shows displayed liquidity sampled at polling times, not a complete event-level book.
- Lead–lag correlation is vulnerable to timestamp mismatch, uneven polling, stale prices and multiple-testing bias.
- No real orders are placed. V4.3 adds virtual wallet simulation and explainable rule-based screening only.
- The AI-style score is not machine learning and is not a probability of profit.
- Virtual wallet state is held in Streamlit session memory and may reset when the app restarts or the session changes.
- Live execution, exchange authentication, order placement, fill reconciliation and production risk controls are not implemented.
""")
