"""
DASHBOARD — WEATHER QUANT BOT v2 FUTURISTIC
Backend idêntico ao original + novos dados: heatmap, scatter, rolling WR, radar.
HTML completamente reescrito com visual nível hard.
"""

import os, json, base64
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    from http.server import ThreadingHTTPServer
except ImportError:
    ThreadingHTTPServer = HTTPServer

from bankroll import dedupe_history_by_market, check_balance_invariant
try:
    from config import START_BALANCE
except Exception:
    START_BALANCE = 100.0

PORT = int(os.environ.get("PORT", 8765))

def load_data():
    errors = []
    db_url = os.environ.get("DATABASE_URL")
    if db_url and db_url.strip():
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM bankroll ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
            conn.close()
            if row: return row[0], None
            errors.append("PostgreSQL: sem registros")
        except Exception as e:
            errors.append(f"PostgreSQL: {str(e)[:80]}")
    else:
        errors.append("DATABASE_URL n\u00e3o configurada")
    try:
        token  = os.environ.get("GITHUB_TOKEN","").strip()
        repo   = os.environ.get("GITHUB_REPO","").strip()
        branch = os.environ.get("GITHUB_BRANCH","main")
        if token and repo:
            import requests as req
            r = req.get(
                f"https://api.github.com/repos/{repo}/contents/bankroll.json",
                headers={"Authorization":f"token {token}"},
                params={"ref":branch},timeout=10)
            if r.status_code == 200:
                data = json.loads(base64.b64decode(r.json()["content"]).decode())
                return data,"\u26a0 GitHub fallback (PostgreSQL indispon\u00edvel)"
            errors.append(f"GitHub HTTP {r.status_code}")
        else:
            errors.append("GITHUB_TOKEN/REPO n\u00e3o configurados")
    except Exception as e:
        errors.append(f"GitHub: {str(e)[:80]}")
    return None," | ".join(errors)


def _max_drawdown(eq):
    if not eq: return 0.0
    peak=eq[0]; mdd=0.0
    for v in eq:
        if v>peak: peak=v
        dd=(peak-v)/peak if peak>0 else 0
        mdd=max(mdd,dd)
    return round(mdd*100,2)

def _drawdown_series(eq):
    if not eq: return []
    peak=eq[0]; out=[]
    for v in eq:
        if v>peak: peak=v
        out.append(round((peak-v)/peak*100,2) if peak>0 else 0)
    return out

def _sharpe(closed):
    if len(closed)<2: return None
    import math
    returns=[float(t.get("pnl") or 0)/float(t.get("stake") or 1) for t in closed]
    mu=sum(returns)/len(returns)
    var=sum((r-mu)**2 for r in returns)/(len(returns)-1)
    std=math.sqrt(var) if var>0 else 0
    return round(mu/std,3) if std>0 else None

def _profit_factor(wins,losses_list):
    gw=sum(float(t.get("pnl") or 0) for t in wins)
    gl=sum(abs(float(t.get("pnl") or 0)) for t in losses_list)
    return round(gw/gl,3) if gl>0 else None

def _calibration_bins(closed,n_bins=5):
    from collections import defaultdict
    bins=defaultdict(list)
    for t in closed:
        prob=t.get("model_prob")
        if prob is None: continue
        p=float(prob)
        if (t.get("side") or "YES").upper()=="NO": p=1.0-p
        b=min(int(p*n_bins),n_bins-1)
        bins[b].append((p,1.0 if t.get("result")=="WIN" else 0.0))
    result=[]
    for b in range(n_bins):
        lo=b/n_bins*100; hi=(b+1)/n_bins*100
        pares=bins.get(b,[])
        if pares:
            predicted=round(sum(p for p,_ in pares)/len(pares)*100,1)
            wr=round(sum(o for _,o in pares)/len(pares)*100,1)
        else:
            predicted=(lo+hi)/2; wr=None
        result.append({"label":f"{lo:.0f}\u2013{hi:.0f}%","predicted":predicted,"actual":wr,"n":len(pares)})
    return result

def _rolling_winrate(closed,window=10):
    if len(closed)<window: return None
    recent=closed[-window:]
    return round(sum(1 for t in recent if t.get("result")=="WIN")/window*100,1)

def _rolling_wr_series(closed,window=10):
    out=[]
    for i in range(len(closed)):
        if i<window-1: out.append(None)
        else:
            subset=closed[i-window+1:i+1]
            out.append(round(sum(1 for t in subset if t.get("result")=="WIN")/window*100,1))
    return out

def _city_date_heatmap(history):
    matrix={}; dates=set()
    for t in history:
        city=t.get("city","?"); mdate=(t.get("market_date") or "")[:10]
        if not mdate: continue
        dates.add(mdate)
        if city not in matrix: matrix[city]={}
        if mdate not in matrix[city]: matrix[city][mdate]={"w":0,"l":0,"o":0}
        r=t.get("result","")
        if r=="WIN": matrix[city][mdate]["w"]+=1
        elif r=="LOSS": matrix[city][mdate]["l"]+=1
        elif r=="OPEN": matrix[city][mdate]["o"]+=1
    return matrix,sorted(dates)

def _scatter_trades(history):
    pts=[]
    for t in history:
        if t.get("result") not in ("WIN","LOSS"): continue
        pts.append({
            "x":(t.get("exit_time") or t.get("market_date") or "")[:10],
            "y":round(float(t.get("pnl") or 0),2),
            "r":max(4,min(16,float(t.get("stake") or 0)*2)),
            "result":t.get("result"),
            "city":t.get("city",""),
        })
    return pts

def build_stats(data):
    raw_history=data.get("history",[])
    history=dedupe_history_by_market(raw_history)
    balance=data.get("balance",0); start=data.get("start_balance",START_BALANCE)
    try: balance_divergence=check_balance_invariant(data)
    except Exception: balance_divergence=0.0
    closed=sorted([t for t in history if t.get("result") in ("WIN","LOSS")],
                  key=lambda x:x.get("exit_time","") or "")
    open_t=[t for t in history if t.get("result")=="OPEN"]
    wins=[t for t in closed if t.get("result")=="WIN"]
    losses=[t for t in closed if t.get("result")=="LOSS"]
    pnl=sum(float(t.get("pnl") or 0) for t in closed)
    exposure=sum(float(t.get("stake") or 0) for t in open_t)
    win_rate=round(len(wins)/len(closed)*100,1) if closed else 0

    city_stats={}
    for t in history:
        c=t.get("city","?")
        if c not in city_stats: city_stats[c]={"wins":0,"losses":0,"pnl":0,"stake":0,"open":0,"open_stake":0}
        if t.get("result")=="WIN": city_stats[c]["wins"]+=1; city_stats[c]["pnl"]+=float(t.get("pnl") or 0)
        elif t.get("result")=="LOSS": city_stats[c]["losses"]+=1; city_stats[c]["pnl"]+=float(t.get("pnl") or 0)
        elif t.get("result")=="OPEN": city_stats[c]["open"]+=1; city_stats[c]["open_stake"]+=float(t.get("stake") or 0)
        city_stats[c]["stake"]+=float(t.get("stake") or 0)

    type_stats={}
    for t in closed:
        tp=(t.get("type") or "?").upper()
        if tp not in type_stats: type_stats[tp]={"wins":0,"losses":0,"pnl":0.0}
        if t.get("result")=="WIN": type_stats[tp]["wins"]+=1
        else: type_stats[tp]["losses"]+=1
        type_stats[tp]["pnl"]+=float(t.get("pnl") or 0)

    equity_curve=[]; running=float(start); eq_vals=[running]
    for t in closed:
        running+=float(t.get("pnl") or 0); eq_vals.append(round(running,2))
        equity_curve.append({"date":(t.get("exit_time","") or "")[:10],"balance":round(running,2),"result":t.get("result",""),"city":t.get("city","")})

    dd_series=_drawdown_series(eq_vals); mdd=_max_drawdown(eq_vals)

    brier_scores=[]
    for _t in closed:
        if _t.get("model_prob") is None: continue
        _prob_yes=float(_t.get("model_prob") or 0)
        _side=(_t.get("side") or "YES").upper()
        _outcome=1.0 if _t.get("result")=="WIN" else 0.0
        _pa=(1.0-_prob_yes) if _side=="NO" else _prob_yes
        brier_scores.append((_pa-_outcome)**2)
    brier=round(sum(brier_scores)/len(brier_scores),4) if brier_scores else None

    avg_edge=round(sum(float(t.get("edge") or 0) for t in history)/len(history)*100,2) if history else 0
    pf=_profit_factor(wins,losses) or 0
    sharpe=_sharpe(closed)
    city_heatmap,heatmap_dates=_city_date_heatmap(history)

    from collections import Counter
    day_counts=Counter()
    for t in closed:
        d=(t.get("exit_time","") or "")[:10]
        if d: day_counts[d]+=1

    return {
        "balance":round(float(balance),2),
        "start_balance":round(float(start),2),
        "balance_divergence":round(float(balance_divergence),2),
        "pnl":round(pnl,2),
        "win_rate":win_rate,
        "win_rate_10":_rolling_winrate(closed,10),
        "total_closed":len(closed),"wins":len(wins),"losses":len(losses),
        "open_count":len(open_t),"exposure":round(exposure,2),
        "brier":brier,"avg_edge":avg_edge,"max_drawdown":mdd,
        "profit_factor":_profit_factor(wins,losses),"sharpe":sharpe,
        "city_stats":city_stats,"type_stats":type_stats,
        "equity_curve":equity_curve,
        "rolling_wr":_rolling_wr_series(closed,10),
        "drawdown_curve":[{"date":equity_curve[i]["date"],"dd":dd_series[i+1]} for i in range(len(equity_curve))],
        "calibration":_calibration_bins(closed),
        "open_trades":open_t,
        "closed_trades":list(reversed(closed))[:50],
        "all_trades":history,
        "city_heatmap":city_heatmap,
        "heatmap_dates":heatmap_dates[-14:],
        "scatter_trades":_scatter_trades(history),
        "trade_density":[{"date":d,"count":c} for d,c in sorted(day_counts.items())],
        "radar":{
            "win_rate":win_rate,
            "profit_factor":min(100,pf*25),
            "sharpe":min(100,max(0,(sharpe or 0)*33)),
            "consistency":round(100-mdd,1),
            "edge_quality":min(100,max(0,avg_edge+50)),
        },
        "duplicate_trades_hidden":max(0,len(raw_history)-len(history)),
        "updated":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


HTML = """<!DOCTYPE html>
<html lang=\"pt\">
<head>
<meta charset=\"UTF-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>WeatherQuant \u26a1 Mission Control</title>
<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
<link href=\"https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Orbitron:wght@400;700;900&display=swap\" rel=\"stylesheet\">
<script src=\"https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js\"></script>
<script src=\"https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js\"></script>
<style>
:root{
  --bg:#010810;--bg1:#020d1c;--bg2:#040f20;
  --cyan:#00d4ff;--green:#00ff88;--red:#ff2d55;--amber:#ffb800;--purple:#c77dff;
  --text:#b8d4f0;--muted:#2a4a6a;--border:rgba(0,180,255,0.1);
  --card:rgba(4,14,28,0.92);
  --mono:'JetBrains Mono',monospace;--display:'Orbitron',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{background:var(--bg);color:var(--text);font-family:var(--mono);font-size:13px;overflow-x:hidden}
::-webkit-scrollbar{width:3px;height:3px}::-webkit-scrollbar-thumb{background:rgba(0,180,255,0.25)}
body::before{content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background-image:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='60' height='104'%3E%3Cpath d='M30 68L2 52V20L30 4l28 16v32zm0 0L60 52M2 52l28 16' fill='none' stroke='rgba(0,180,255,0.035)' stroke-width='1'/%3E%3C/svg%3E\");opacity:.7}
.wrapper{position:relative;z-index:1;max-width:1800px;margin:0 auto;padding:14px 16px}
.ticker{overflow:hidden;height:26px;display:flex;align-items:center;background:rgba(0,180,255,0.02);border-bottom:1px solid var(--border);margin-bottom:0}
.ticker-inner{display:flex;gap:48px;animation:ticker 50s linear infinite;white-space:nowrap;padding:0 20px;font-size:10px;color:var(--muted)}
@keyframes ticker{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
.tw{color:var(--green)}.tl{color:var(--red)}.to{color:var(--amber)}
header{display:flex;align-items:center;justify-content:space-between;padding:12px 0 14px;border-bottom:1px solid var(--border);gap:8px;flex-wrap:wrap}
.logo{font-family:var(--display);font-size:17px;font-weight:900;letter-spacing:2px;color:#fff;text-shadow:0 0 40px rgba(0,212,255,0.5);white-space:nowrap}
.logo em{color:var(--cyan);font-style:normal}
.hdr-r{display:flex;align-items:center;gap:10px;flex-shrink:0}
.spill{display:flex;align-items:center;gap:5px;background:rgba(0,255,136,0.05);border:1px solid rgba(0,255,136,0.12);border-radius:20px;padding:3px 10px;font-size:10px;color:var(--green);font-family:var(--display);letter-spacing:.1em}
.sdot{width:5px;height:5px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.ts{color:var(--muted);font-size:10px;display:none}
@media(min-width:600px){.ts{display:inline}}
.rbtn2{background:transparent;border:1px solid var(--border);color:var(--muted);padding:4px 12px;border-radius:4px;cursor:pointer;font-family:var(--mono);font-size:10px;transition:.2s}
.rbtn2:hover{border-color:var(--cyan);color:var(--cyan);box-shadow:0 0 12px rgba(0,212,255,0.2)}
.wbar{background:rgba(255,184,0,.06);border-bottom:1px solid rgba(255,184,0,.15);padding:5px 16px;font-size:10px;color:var(--amber);display:none}
.ibar{display:flex;gap:12px;padding:8px 12px;background:rgba(0,212,255,.02);border:1px solid var(--border);border-radius:6px;margin:12px 0;flex-wrap:wrap;align-items:center}
.ii{font-size:10px;color:var(--muted)}.ii strong{color:var(--text)}
.idiv{width:1px;height:12px;background:var(--border);display:none}
@media(min-width:600px){.idiv{display:block}}
.krow{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:12px}
@media(min-width:600px){.krow{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(min-width:1000px){.krow{grid-template-columns:repeat(6,minmax(0,1fr))}}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:7px;padding:12px 14px;position:relative;overflow:hidden;transition:.25s;cursor:default}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--acc,var(--cyan)),transparent)}
.kpi::after{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(0,212,255,.025) 0%,transparent 60%);pointer-events:none}
.kpi:hover{border-color:rgba(0,212,255,.2);transform:translateY(-2px);box-shadow:0 0 20px rgba(0,212,255,.1)}
.kl{font-family:var(--display);font-size:8px;text-transform:uppercase;letter-spacing:.18em;color:var(--muted);margin-bottom:8px}
.kv{font-family:var(--display);font-size:20px;font-weight:900;color:#fff;line-height:1}
.ks{font-size:9px;color:var(--muted);margin-top:5px}
.hero{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;margin-bottom:12px}
@media(min-width:900px){.hero{grid-template-columns:minmax(0,1.35fr) minmax(0,1fr)}}
.card{background:var(--card);border:1px solid var(--border);border-radius:7px;padding:15px;position:relative;overflow:hidden;min-width:0}
.card::before{content:'';position:absolute;top:0;left:-120%;width:50%;height:1px;background:linear-gradient(90deg,transparent,var(--cyan),transparent);animation:scan 5s ease-in-out infinite;opacity:.3}
@keyframes scan{0%,100%{left:-120%}55%{left:220%}}
.ct{font-family:var(--display);font-size:8px;text-transform:uppercase;letter-spacing:.2em;color:var(--muted);margin-bottom:12px;display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.ct::before{content:'';width:2px;height:10px;background:var(--cyan);border-radius:1px;box-shadow:0 0 5px var(--cyan);flex-shrink:0}
#gwrap{position:relative;height:300px;cursor:grab;width:100%}
@media(min-width:900px){#gwrap{height:370px}}
#gwrap:active{cursor:grabbing}
#gcanvas{width:100% !important;height:100% !important;display:block}
.gtip{position:absolute;background:rgba(1,10,24,.97);border:1px solid rgba(0,212,255,.4);border-radius:5px;padding:9px 13px;font-size:10px;pointer-events:none;display:none;z-index:10;min-width:140px;box-shadow:0 0 16px rgba(0,212,255,.2)}
.gtip strong{color:var(--cyan);display:block;margin-bottom:5px;font-size:11px;font-family:var(--display);letter-spacing:.05em}
.gs{display:flex;justify-content:space-between;gap:14px;font-size:10px;margin-top:1px}
.gs span:first-child{color:var(--muted)}
.g2{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;margin-bottom:12px}
@media(min-width:700px){.g2{grid-template-columns:repeat(2,minmax(0,1fr))}}
.g3{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;margin-bottom:12px}
@media(min-width:700px){.g3{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(min-width:1100px){.g3{grid-template-columns:repeat(3,minmax(0,1fr))}}
.g32{display:grid;grid-template-columns:minmax(0,1fr);gap:12px;margin-bottom:12px}
@media(min-width:900px){.g32{grid-template-columns:minmax(0,2fr) minmax(0,1fr)}}
.fbar{background:var(--card);border:1px solid var(--border);border-radius:7px;padding:9px 14px;margin-bottom:12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.fl{font-family:var(--display);font-size:8px;text-transform:uppercase;letter-spacing:.18em;color:var(--muted)}
.chips{display:flex;gap:4px;flex-wrap:wrap}
.chip{background:rgba(0,180,255,.03);border:1px solid var(--border);border-radius:14px;padding:2px 9px;font-size:10px;cursor:pointer;transition:.2s;color:var(--muted)}
.chip:hover,.chip.on{background:rgba(0,212,255,.08);border-color:rgba(0,212,255,.3);color:var(--cyan)}
.rbt{background:transparent;border:1px solid var(--border);border-radius:3px;padding:2px 9px;font-family:var(--mono);font-size:10px;color:var(--muted);cursor:pointer;transition:.2s}
.rbt:hover{border-color:var(--cyan)}.rbt.ra{background:rgba(0,212,255,.07);border-color:var(--cyan);color:var(--cyan)}
.rbt.rw{background:rgba(0,255,136,.07);border-color:var(--green);color:var(--green)}
.rbt.rl{background:rgba(255,45,85,.07);border-color:var(--red);color:var(--red)}
.hmwrap{overflow:auto;max-height:320px;width:100%}
#hmcanvas{display:block;max-width:100%}
.tcard{background:var(--card);border:1px solid var(--border);border-radius:7px;margin-bottom:12px;overflow:hidden}
.thead2{padding:10px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px}
.twrap{max-height:340px;overflow-y:auto;overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:500px}
th{padding:7px 11px;text-align:left;font-family:var(--display);font-size:8px;text-transform:uppercase;letter-spacing:.14em;color:var(--muted);border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg2);z-index:1;white-space:nowrap}
td{padding:7px 11px;border-bottom:1px solid rgba(0,180,255,.03);font-size:11px}
tr:hover td{background:rgba(0,212,255,.02)}
.ctag{display:inline-block;padding:1px 6px;border-radius:9px;background:rgba(0,212,255,.07);color:var(--cyan);font-size:9px;border:1px solid rgba(0,212,255,.12);white-space:nowrap}
.bw{color:var(--green)}.bl{color:var(--red)}.bo{color:var(--amber)}
.pb{display:flex;align-items:center;gap:4px;min-width:60px}
.pbg{flex:1;height:2px;background:rgba(255,255,255,.06);border-radius:1px;overflow:hidden}
.pbf{height:100%;border-radius:1px}
.empty2{color:var(--muted);text-align:center;padding:28px;font-size:11px}
.gw{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:4px;min-height:160px}
.gnum{font-family:var(--display);font-size:38px;font-weight:900;color:#fff;text-align:center;line-height:1}
.gsub{font-size:10px;color:var(--muted);text-align:center}
.card,.kpi,.tcard{transition:border-color .25s,box-shadow .25s,transform .25s}
.ch{position:relative}.ch canvas{position:absolute;top:0;left:0;width:100% !important;height:100% !important}
</style>
</head>
<body>
<div id=\"wbar\" class=\"wbar\"></div>
<div class=\"wrapper\">
<header>
  <div class=\"logo\">\u26a1 WEATHER<em>QUANT</em></div>
  <div class=\"hdr-r\">
    <div class=\"spill\"><div class=\"sdot\"></div>LIVE</div>
    <span class=\"ts\" id=\"ts\">\u2014</span>
    <button class=\"rbtn2\" onclick=\"fetchData()\">\u21bb SYNC</button>
  </div>
</header>
<div class=\"ticker\"><div class=\"ticker-inner\" id=\"tkr\"></div></div>
<div class=\"ibar\">
  <div class=\"ii\">Abertos: <strong id=\"iO\">\u2014</strong></div><div class=\"idiv\"></div>
  <div class=\"ii\">Exposi\u00e7\u00e3o: <strong id=\"iE\">\u2014</strong></div><div class=\"idiv\"></div>
  <div class=\"ii\">Edge m\u00e9dio: <strong id=\"iEd\">\u2014</strong></div><div class=\"idiv\"></div>
  <div class=\"ii\">Brier: <strong id=\"iB\">\u2014</strong></div><div class=\"idiv\"></div>
  <div class=\"ii\">WR \u00faltimos 10: <strong id=\"iW\">\u2014</strong></div>
</div>
<div class=\"krow\">
  <div class=\"kpi\" style=\"--acc:var(--cyan)\"><div class=\"kl\">Saldo</div><div class=\"kv\" id=\"kBal\">\u2014</div><div class=\"ks\" id=\"kBalS\">\u2014</div></div>
  <div class=\"kpi\" style=\"--acc:var(--green)\"><div class=\"kl\">PnL Total</div><div class=\"kv\" id=\"kPnl\">\u2014</div><div class=\"ks\" id=\"kPnlS\">\u2014</div></div>
  <div class=\"kpi\" style=\"--acc:var(--purple)\"><div class=\"kl\">Win Rate</div><div class=\"kv\" id=\"kWR\">\u2014</div><div class=\"ks\" id=\"kWRS\">\u2014</div></div>
  <div class=\"kpi\" style=\"--acc:var(--amber)\"><div class=\"kl\">Profit Factor</div><div class=\"kv\" id=\"kPF\">\u2014</div><div class=\"ks\">&ge;1.5 = excelente</div></div>
  <div class=\"kpi\" style=\"--acc:var(--red)\"><div class=\"kl\">Max Drawdown</div><div class=\"kv\" id=\"kMDD\">\u2014</div><div class=\"ks\">queda m\u00e1x do pico</div></div>
  <div class=\"kpi\" style=\"--acc:#4dd0e1\"><div class=\"kl\">Sharpe Ratio</div><div class=\"kv\" id=\"kSh\">\u2014</div><div class=\"ks\">&gt;1 = bom</div></div>
</div>
<div class=\"hero\">
  <div class=\"card\">
    <div class=\"ct\">&#127757; GLOBE \u2014 drag para girar \u00b7 hover para stats</div>
    <div id=\"gwrap\"><canvas id=\"gcanvas\"></canvas><div class=\"gtip\" id=\"gtip\"></div></div>
  </div>
  <div class=\"card\" style=\"display:flex;flex-direction:column;gap:12px\">
    <div><div class=\"ct\">&#128200; EQUITY CURVE</div><div class=\"ch\" style=\"height:175px\"><canvas id=\"eqC\"></canvas></div></div>
    <div><div class=\"ct\">&#128201; DRAWDOWN</div><div class=\"ch\" style=\"height:95px\"><canvas id=\"ddC\"></canvas></div></div>
  </div>
</div>
<div class=\"g32\">
  <div class=\"card\">
    <div class=\"ct\">&#127777; HEATMAP \u2014 Cidade \u00d7 Data &nbsp;
      <span style=\"color:var(--green);font-size:9px\">\u25a0 Win</span>&nbsp;
      <span style=\"color:var(--red);font-size:9px\">\u25a0 Loss</span>&nbsp;
      <span style=\"color:var(--amber);font-size:9px\">\u25a0 Aberto</span>
    </div>
    <div class=\"hmwrap\"><canvas id=\"hmcanvas\"></canvas></div>
  </div>
  <div class=\"card\">
    <div class=\"ct\">&#127919; WIN RATE GAUGE</div>
    <div class=\"gw\">
      <canvas id=\"gchart\" width=\"200\" height=\"110\"></canvas>
      <div class=\"gnum\" id=\"gnum\">\u2014</div>
      <div class=\"gsub\" id=\"gsub\">\u2014</div>
    </div>
  </div>
</div>
<div class=\"fbar\">
  <span class=\"fl\">Cidade</span>
  <div class=\"chips\" id=\"chips\"></div>
  <span class=\"fl\">Resultado</span>
  <div style=\"display:flex;gap:4px\">
    <button class=\"rbt ra\" onclick=\"setR(this,'all')\">Todos</button>
    <button class=\"rbt\" onclick=\"setR(this,'OPEN')\">Abertos</button>
    <button class=\"rbt\" onclick=\"setR(this,'WIN')\">Win</button>
    <button class=\"rbt\" onclick=\"setR(this,'LOSS')\">Loss</button>
  </div>
</div>
<div class=\"g3\">
  <div class=\"card\"><div class=\"ct\">&#128176; PnL POR CIDADE</div><div class=\"ch\" style=\"height:200px\"><canvas id=\"cchart\"></canvas></div></div>
  <div class=\"card\"><div class=\"ct\">\u26a1 PnL POR TIPO</div><div class=\"ch\" style=\"height:200px\"><canvas id=\"tchart\"></canvas></div></div>
  <div class=\"card\"><div class=\"ct\">&#128300; CALIBRA\u00c7\u00c3O</div><div class=\"ch\" style=\"height:200px\"><canvas id=\"calC\"></canvas></div></div>
</div>
<div class=\"g3\">
  <div class=\"card\"><div class=\"ct\">&#128202; ROLLING WIN RATE (10 trades)</div><div class=\"ch\" style=\"height:160px\"><canvas id=\"rwC\"></canvas></div></div>
  <div class=\"card\"><div class=\"ct\">\ud83c\udfaf DISTRIBUI\u00c7\u00c3O DE EDGE</div><div class=\"ch\" style=\"height:160px\"><canvas id=\"edC\"></canvas></div></div>
  <div class=\"card\"><div class=\"ct\">&#128197; TRADES POR DIA</div><div class=\"ch\" style=\"height:160px\"><canvas id=\"dnC\"></canvas></div></div>
</div>
<div class=\"g2\">
  <div class=\"card\">
    <div class=\"ct\">&#127919; PERFORMANCE RADAR</div>
    <div class=\"ch\" style=\"height:240px\">
      <canvas id=\"rdC\"></canvas>
    </div>
  </div>
  <div class=\"card\">
    <div class=\"ct\">&#128308; SCATTER \u2014 PnL por Trade (tamanho = stake)</div>
    <div class=\"ch\" style=\"height:220px\"><canvas id=\"scC\"></canvas></div>
  </div>
</div>
<div class=\"tcard\">
  <div class=\"thead2\">
    <div class=\"ct\" style=\"margin:0\">\u23f3 POSI\u00c7\u00d5ES ABERTAS</div>
    <span id=\"oC\" style=\"color:var(--amber);font-size:10px\"></span>
  </div>
  <div class=\"twrap\"><table><thead><tr>
    <th>Cidade</th><th>Data</th><th>Side</th><th>Tipo</th><th>Stake</th>
    <th>Prob</th><th>Entry</th><th>Edge</th><th>Pergunta</th>
  </tr></thead><tbody id=\"oBody\"></tbody></table></div>
</div>
<div class=\"tcard\">
  <div class=\"thead2\">
    <div class=\"ct\" style=\"margin:0\">&#128203; TRADES FECHADOS</div>
    <span id=\"cC\" style=\"color:var(--muted);font-size:10px\"></span>
  </div>
  <div class=\"twrap\"><table><thead><tr>
    <th></th><th>Cidade</th><th>Data</th><th>Side</th><th>Target</th>
    <th>Stake</th><th>PnL</th><th>Prob</th><th>Entry</th><th>Temp Real</th>
  </tr></thead><tbody id=\"cBody\"></tbody></table></div>
</div>
</div>
<script>
let D=null,aC='all',aR='all',ch={};
async function fetchData(){try{const r=await fetch('/api/stats');if(!r.ok)throw new Error(r.status);D=await r.json();render()}catch(e){console.error(e)}}
fetchData();setInterval(fetchData,20000);
let _firstRender=true;
function render(){if(!D)return;
  wbar();kpis();infoBar();ticker();buildChips();
  equity();drawdown();heatmap();gauge();
  cityChart();typeChart();calibration();rollingWR();edgeChart();density();radar();scatter();
  tables();globe();
  document.getElementById('ts').textContent=D.updated||'';
  _firstRender=false;
}
function $(id){return document.getElementById(id)}
function mkC(id,cfg){if(ch[id])ch[id].destroy();ch[id]=new Chart($(id).getContext('2d'),cfg);return ch[id]}
function sg(v){return v>=0?'+':''}
function wbar(){const b=$('wbar');if(D.warning){b.style.display='block';b.textContent=D.warning}else b.style.display='none'}
function ticker(){
  const items=(D.closed_trades||[]).slice(0,10).map(t=>{
    const c=t.result==='WIN'?'tw':'tl';const s=t.result==='WIN'?'\u25b2':'\u25bc';
    return`<span style=\"display:inline-flex;align-items:center;gap:5px\"><span class=\"${c}\">${s} ${t.city}</span><span>${t.type} ${t.target}\u00b0${t.unit}</span><span class=\"${c}\">${sg(t.pnl)}$${Math.abs(t.pnl).toFixed(2)}</span></span>`;
  });
  const all=items.join('<span style=\"margin:0 16px;color:var(--border)\">|</span>');
  $('tkr').innerHTML=all+all;
}
function kpis(){
  const d=D;
  const pp=d.start_balance>0?((d.balance-d.start_balance)/d.start_balance*100).toFixed(1):0;
  $('kBal').textContent='$'+d.balance.toFixed(2);
  $('kBalS').textContent=sg(d.balance-d.start_balance)+'$'+Math.abs(d.balance-d.start_balance).toFixed(2)+' vs in\u00edcio';
  const pe=$('kPnl');pe.textContent=sg(d.pnl)+'$'+Math.abs(d.pnl).toFixed(2);
  pe.style.color=d.pnl>=0?'var(--green)':'var(--red)';
  $('kPnlS').textContent=sg(parseFloat(pp))+pp+'% retorno';
  $('kWR').textContent=d.win_rate+'%';
  $('kWRS').textContent=d.wins+'W / '+d.losses+'L ('+d.total_closed+')';
  const pf=$('kPF');
  if(d.profit_factor!=null){pf.textContent=d.profit_factor.toFixed(2)+'\u00d7';pf.style.color=d.profit_factor>=1.5?'var(--green)':d.profit_factor>=1?'var(--amber)':'var(--red)'}else pf.textContent='N/A';
  const md=$('kMDD');md.textContent=(d.max_drawdown||0).toFixed(1)+'%';md.style.color=d.max_drawdown>40?'var(--red)':d.max_drawdown>20?'var(--amber)':'var(--green)';
  const sh=$('kSh');
  if(d.sharpe!=null){sh.textContent=d.sharpe.toFixed(2);sh.style.color=d.sharpe>=1?'var(--green)':d.sharpe>=0?'var(--amber)':'var(--red)'}else sh.textContent='N/A';
}
function infoBar(){
  $('iO').textContent=D.open_count+' ($'+D.exposure.toFixed(2)+')';
  $('iEd').textContent=sg(D.avg_edge)+D.avg_edge.toFixed(1)+'%';
  $('iB').textContent=D.brier!=null?D.brier:'N/A';
  const w=$('iW');
  if(D.win_rate_10!=null){w.textContent=D.win_rate_10+'%';w.style.color=D.win_rate_10>=55?'var(--green)':D.win_rate_10>=45?'var(--amber)':'var(--red)'}else w.textContent='N/A';
}
function buildChips(){
  const wrap=$('chips');const cities=['all',...Object.keys(D.city_stats)];
  const cur=[...wrap.querySelectorAll('.chip')].map(b=>b.dataset.c);
  if(!_firstRender&&cur.join(',')=== cities.join(','))return;
  wrap.innerHTML='';
  cities.forEach(c=>{
    const b=document.createElement('button');b.className='chip'+(c===aC?' on':'');
    b.dataset.c=c;b.textContent=c==='all'?'Todas':c;
    b.onclick=()=>{aC=c;[...wrap.querySelectorAll('.chip')].forEach(x=>x.classList.remove('on'));b.classList.add('on');cityChart();tables()};
    wrap.appendChild(b);
  });
}
function setR(el,r){aR=r;document.querySelectorAll('.rbt').forEach(b=>b.className='rbt');el.className='rbt '+(r==='all'?'ra':r==='WIN'?'rw':'rl');tables()}
const SC={x:{grid:{color:'rgba(0,180,255,.04)'},ticks:{color:'#2a4a6a',font:{size:9}}},y:{grid:{color:'rgba(0,180,255,.04)'},ticks:{color:'#2a4a6a',font:{size:9}}}};
function equity(){
  const eq=D.equity_curve;const ctx=$('eqC').getContext('2d');
  const g=ctx.createLinearGradient(0,0,0,175);g.addColorStop(0,'rgba(0,212,255,.28)');g.addColorStop(1,'rgba(0,212,255,0)');
  mkC('eqC',{type:'line',data:{labels:eq.map(p=>p.date),datasets:[{data:eq.map(p=>p.balance),borderColor:'#00d4ff',backgroundColor:g,fill:true,tension:.4,
    pointRadius:eq.map((_,i)=>i===eq.length-1?5:2),pointBackgroundColor:eq.map(p=>p.result==='WIN'?'#00ff88':'#ff2d55'),pointBorderColor:'#010810',pointBorderWidth:2,borderWidth:2}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>' $'+c.parsed.y.toFixed(2)}}},
      scales:{x:{...SC.x,ticks:{...SC.x.ticks,maxTicksLimit:8,maxRotation:0}},y:{...SC.y,ticks:{...SC.y.ticks,callback:v=>'$'+v.toFixed(0)}}}}});
}
function drawdown(){
  const dc=D.drawdown_curve||[];const ctx=$('ddC').getContext('2d');
  const g=ctx.createLinearGradient(0,0,0,95);g.addColorStop(0,'rgba(255,45,85,.35)');g.addColorStop(1,'rgba(255,45,85,0)');
  mkC('ddC',{type:'line',data:{labels:dc.map(p=>p.date),datasets:[{data:dc.map(p=>p.dd),borderColor:'#ff2d55',backgroundColor:g,fill:true,tension:.3,pointRadius:0,borderWidth:1.5}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{x:{...SC.x,ticks:{...SC.x.ticks,maxTicksLimit:6,maxRotation:0}},y:{...SC.y,ticks:{...SC.y.ticks,callback:v=>v+'%'},reverse:true}}}});
}
function heatmap(){
  const mx=D.city_heatmap||{};const dates=D.heatmap_dates||[];
  const cities=Object.keys(mx);if(!cities.length||!dates.length)return;
  const cW=30,cH=19,lW=108,hH=48,pd=3;
  const W=lW+dates.length*(cW+pd)+16,H=hH+cities.length*(cH+pd)+8;
  const cv=$('hmcanvas');cv.width=W;cv.height=H;
  const ctx=cv.getContext('2d');ctx.clearRect(0,0,W,H);
  ctx.font='9px JetBrains Mono';ctx.fillStyle='#2a4a6a';
  dates.forEach((d,i)=>{
    const x=lW+i*(cW+pd)+cW/2;ctx.save();ctx.translate(x,hH-2);ctx.rotate(-Math.PI/3.5);ctx.fillText(d.slice(5),0,0);ctx.restore();
  });
  cities.forEach((city,ci)=>{
    const y=hH+ci*(cH+pd);
    ctx.font='10px JetBrains Mono';ctx.fillStyle='#7ab4d0';ctx.textAlign='right';
    ctx.fillText(city.length>13?city.slice(0,13):city,lW-5,y+cH/2+3);ctx.textAlign='left';
    dates.forEach((d,di)=>{
      const x=lW+di*(cW+pd);const cell=(mx[city]||{})[d];
      if(!cell){ctx.fillStyle='rgba(0,180,255,.03)';ctx.beginPath();ctx.roundRect(x,y,cW,cH,2);ctx.fill()}
      else{
        const{w,l,o}=cell;
        let col;
        if(w>0&&l===0&&o===0)col=`rgba(0,255,136,${Math.min(.9,.5+w*.15)})`;
        else if(l>0&&w===0&&o===0)col=`rgba(255,45,85,${Math.min(.9,.5+l*.15)})`;
        else if(o>0&&w===0&&l===0)col='rgba(255,184,0,.6)';
        else col='rgba(199,125,255,.6)';
        ctx.fillStyle=col;ctx.beginPath();ctx.roundRect(x,y,cW,cH,2);ctx.fill();
        if(w+l+o>1){ctx.font='8px JetBrains Mono';ctx.fillStyle='rgba(255,255,255,.8)';ctx.textAlign='center';ctx.fillText(w+l+o,x+cW/2,y+cH/2+3);ctx.textAlign='left'}
      }
    });
  });
}
function gauge(){
  const wr=D.win_rate/100;const c=$('gchart');const ctx=c.getContext('2d');
  ctx.clearRect(0,0,200,110);
  const cx=100,cy=100,r=78;
  ctx.beginPath();ctx.arc(cx,cy,r,Math.PI,2*Math.PI);ctx.strokeStyle='rgba(255,255,255,.04)';ctx.lineWidth=13;ctx.lineCap='round';ctx.stroke();
  const col=wr>=.55?'#00ff88':wr>=.45?'#ffb800':'#ff2d55';
  const g=ctx.createLinearGradient(cx-r,cy,cx+r,cy);g.addColorStop(0,'#00d4ff');g.addColorStop(1,col);
  ctx.beginPath();ctx.arc(cx,cy,r,Math.PI,Math.PI+Math.PI*wr);ctx.strokeStyle=g;ctx.lineWidth=13;ctx.lineCap='round';ctx.stroke();
  ctx.beginPath();ctx.arc(cx,cy,r,Math.PI,Math.PI+Math.PI*wr);ctx.strokeStyle=col;ctx.lineWidth=5;ctx.globalAlpha=.25;ctx.stroke();ctx.globalAlpha=1;
  $('gnum').textContent=D.win_rate+'%';$('gnum').style.color=col;
  $('gsub').textContent=D.wins+'W / '+D.losses+'L \u00b7 '+D.total_closed+' fechados';
}
function cityChart(){
  const cs=D.city_stats;
  let entries=Object.entries(cs).filter(([c])=>aC==='all'||c===aC);entries.sort((a,b)=>b[1].pnl-a[1].pnl);
  const v=entries.map(e=>e[1].pnl);
  mkC('cchart',{type:'bar',data:{labels:entries.map(e=>e[0]),datasets:[{data:v,backgroundColor:v.map(x=>x>=0?'rgba(0,255,136,.6)':'rgba(255,45,85,.6)'),borderColor:v.map(x=>x>=0?'#00ff88':'#ff2d55'),borderWidth:1,borderRadius:3}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` $${c.parsed.x.toFixed(2)}`}}},
      scales:{x:{...SC.x,ticks:{...SC.x.ticks,callback:v=>'$'+v.toFixed(0)}},y:{grid:{display:false},ticks:{color:'#b8d4f0',font:{size:10}}}}}});
}
function typeChart(){
  const ts=D.type_stats||{};const types=Object.keys(ts);if(!types.length)return;
  const p=types.map(t=>ts[t].pnl||0);
  const wrs=types.map(t=>{const n=ts[t].wins+ts[t].losses;return n?Math.round(ts[t].wins/n*100):0});
  mkC('tchart',{type:'bar',data:{labels:types.map((t,i)=>`${t} (${wrs[i]}% WR)`),datasets:[{data:p,backgroundColor:p.map(v=>v>=0?'rgba(0,255,136,.6)':'rgba(255,45,85,.6)'),borderColor:p.map(v=>v>=0?'#00ff88':'#ff2d55'),borderWidth:1,borderRadius:4}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` $${c.parsed.y.toFixed(2)}`}}},
      scales:{x:{grid:{display:false},ticks:{color:'#b8d4f0',font:{size:10}}},y:{...SC.y,ticks:{...SC.y.ticks,callback:v=>'$'+v.toFixed(0)}}}}});
}
function calibration(){
  const cal=D.calibration||[];
  mkC('calC',{type:'bar',data:{labels:cal.map(b=>b.label),datasets:[
    {label:'Modelo',data:cal.map(b=>b.predicted),backgroundColor:'rgba(0,212,255,.2)',borderColor:'#00d4ff',borderWidth:1,borderRadius:3},
    {label:'Real WR',data:cal.map(b=>b.actual),backgroundColor:'rgba(0,255,136,.5)',borderColor:'#00ff88',borderWidth:1,borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:true,labels:{color:'#7ab4d0',font:{size:8},boxWidth:8}}},
      scales:{x:SC.x,y:{...SC.y,ticks:{...SC.y.ticks,callback:v=>v+'%'},min:0,max:100}}}});

}
function rollingWR(){
  const eq=D.equity_curve||[];const rw=D.rolling_wr||[];
  mkC('rwC',{type:'line',data:{labels:eq.map(p=>p.date),datasets:[
    {data:rw,borderColor:'#c77dff',backgroundColor:'rgba(199,125,255,.08)',fill:true,tension:.4,pointRadius:0,borderWidth:2,spanGaps:true},
    {data:eq.map(()=>52),borderColor:'rgba(255,184,0,.3)',borderDash:[4,4],borderWidth:1,pointRadius:0,fill:false}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{x:{...SC.x,ticks:{...SC.x.ticks,maxTicksLimit:6,maxRotation:0}},y:{...SC.y,ticks:{...SC.y.ticks,callback:v=>v+'%'},min:0,max:100}}}});
}
function edgeChart(){
  const edges=(D.all_trades||[]).filter(t=>t.edge!=null).map(t=>Math.round(t.edge*100));
  const bk={};edges.forEach(e=>{const b=Math.floor(e/5)*5;bk[b]=(bk[b]||0)+1});
  const keys=Object.keys(bk).sort((a,b)=>+a-+b);
  mkC('edC',{type:'bar',data:{labels:keys.map(k=>k+'%'),datasets:[{data:keys.map(k=>bk[k]),backgroundColor:'rgba(199,125,255,.55)',borderColor:'#c77dff',borderWidth:1,borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:SC.x,y:SC.y}}});
}
function density(){
  const td=D.trade_density||[];
  mkC('dnC',{type:'bar',data:{labels:td.map(d=>d.date.slice(5)),datasets:[{data:td.map(d=>d.count),backgroundColor:'rgba(0,212,255,.45)',borderColor:'#00d4ff',borderWidth:1,borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{...SC.x,ticks:{...SC.x.ticks,maxRotation:45}},y:SC.y}}});
}
function radar(){
  const r=D.radar||{};
  mkC('rdC',{type:'radar',data:{labels:['Win Rate','Profit Factor','Sharpe','Consist\u00eancia','Edge Quality'],
    datasets:[{data:[r.win_rate||0,r.profit_factor||0,r.sharpe||0,r.consistency||0,r.edge_quality||0],
      backgroundColor:'rgba(0,212,255,.1)',borderColor:'#00d4ff',borderWidth:2,
      pointBackgroundColor:'#00d4ff',pointRadius:4,pointHoverRadius:6}]},
    options:{responsive:true,maintainAspectRatio:true,plugins:{legend:{display:false}},
      scales:{r:{min:0,max:100,grid:{color:'rgba(0,180,255,.07)'},angleLines:{color:'rgba(0,180,255,.07)'},
        pointLabels:{color:'#4a7090',font:{size:9,family:'JetBrains Mono'}},ticks:{display:false}}}}});
}
function scatter(){
  const pts=D.scatter_trades||[];
  const dates=[...new Set(pts.map(p=>p.x))].sort();
  const di=Object.fromEntries(dates.map((d,i)=>[d,i]));
  const wins=pts.filter(p=>p.result==='WIN').map(p=>({x:di[p.x],y:p.y,r:p.r,city:p.city,date:p.x}));
  const losses=pts.filter(p=>p.result==='LOSS').map(p=>({x:di[p.x],y:p.y,r:p.r,city:p.city,date:p.x}));
  mkC('scC',{type:'bubble',data:{datasets:[
    {label:'WIN',data:wins,backgroundColor:'rgba(0,255,136,.5)',borderColor:'#00ff88',borderWidth:1},
    {label:'LOSS',data:losses,backgroundColor:'rgba(255,45,85,.5)',borderColor:'#ff2d55',borderWidth:1}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>`${c.raw.city}: ${c.raw.y>=0?'+':''}$${c.raw.y.toFixed(2)} (${c.raw.date})`}}},
      scales:{x:{...SC.x,ticks:{...SC.x.ticks,callback:v=>dates[v]?dates[v].slice(5):''}},
        y:{...SC.y,ticks:{...SC.y.ticks,callback:v=>'$'+v.toFixed(0)}}}}});
}
function tables(){
  const open=(D.open_trades||[]).filter(t=>aC==='all'||t.city===aC);
  $('oC').textContent=open.length+' posi\u00e7\u00f5es';
  $('oBody').innerHTML=open.length?open.map(t=>{
    const s=t.side||'YES';const pa=t.model_prob!=null?(s==='NO'?Math.round((1-t.model_prob)*100):Math.round(t.model_prob*100)):null;
    const sc=s==='NO'?'var(--amber)':'var(--cyan)';const ep=Math.round((t.entry_price||t.market_price||0)*100);
    const e=((t.edge||0)*100).toFixed(1);
    return`<tr><td><span class=\"ctag\">${t.city||'\u2014'}</span></td><td>${t.market_date||'\u2014'}</td><td><b style=\"color:${sc}\">${s}</b></td><td style=\"color:var(--amber)\">${t.type||'\u2014'}</td><td>$${(t.stake||0).toFixed(2)}</td>
    <td><div class=\"pb\"><div class=\"pbg\"><div class=\"pbf\" style=\"width:${pa||0}%;background:${sc}\"></div></div>${pa!=null?pa+'%':'\u2014'}</div></td>
    <td>${ep}%</td><td class=\"${parseFloat(e)>=0?'bw':'bl'}\">${parseFloat(e)>=0?'+':''}${e}%</td>
    <td style=\"color:var(--muted);font-size:10px\">${(t.question||'').substring(0,46)}\u2026</td></tr>`;
  }).join(''):'<tr><td colspan=\"9\" class=\"empty2\">Nenhuma posi\u00e7\u00e3o aberta</td></tr>';
  const closed=(D.closed_trades||[]).filter(t=>{
    if(aC!=='all'&&t.city!==aC)return false;
    if(aR==='all'||aR==='OPEN')return true;return t.result===aR;
  });
  $('cC').textContent=closed.length+' trades';
  $('cBody').innerHTML=closed.length?closed.map(t=>{
    const iw=t.result==='WIN';const pnl=t.pnl||0;const s=t.side||'YES';
    const pa=t.model_prob!=null?(s==='NO'?Math.round((1-t.model_prob)*100):Math.round(t.model_prob*100)):null;
    const sc=s==='NO'?'var(--amber)':'var(--cyan)';const ep=Math.round((t.entry_price||t.market_price||0)*100);
    return`<tr><td style=\"font-size:15px;${iw?'color:var(--green);text-shadow:0 0 6px rgba(0,255,136,.5)':'color:var(--red)'}\">${iw?'\u2713':'\u2717'}</td>
    <td><span class=\"ctag\">${t.city||'\u2014'}</span></td><td>${t.market_date||'\u2014'}</td><td><b style=\"color:${sc}\">${s}</b></td>
    <td style=\"color:var(--muted)\">${t.type||''} ${t.target||''}\u00b0${t.unit||'C'}</td><td>$${(t.stake||0).toFixed(2)}</td>
    <td style=\"font-weight:700;${pnl>=0?'color:var(--green);text-shadow:0 0 5px rgba(0,255,136,.4)':'color:var(--red)'}\">${pnl>=0?'+':''}$${Math.abs(pnl).toFixed(2)}</td>
    <td>${pa!=null?pa+'%':'\u2014'}</td><td>${ep}%</td>
    <td style=\"color:var(--cyan)\">${t.real_temp_c!=null?t.real_temp_c.toFixed(1)+'\u00b0C':'\u2014'}</td></tr>`;
  }).join(''):'<tr><td colspan=\"10\" class=\"empty2\">Nenhum trade fechado</td></tr>';
}
const CC={'New York':[40.71,-74.01],'London':[51.51,-0.13],'Paris':[48.86,2.35],'Hong Kong':[22.32,114.17],'Tokyo':[35.68,139.65],'Seoul':[37.57,126.98],'Beijing':[39.90,116.41],'S\u00e3o Paulo':[-23.55,-46.63],'Milan':[45.46,9.19],'Los Angeles':[34.05,-118.24],'Houston':[29.76,-95.37],'Austin':[30.27,-97.74],'Denver':[39.74,-104.99],'Seattle':[47.61,-122.33],'Chicago':[41.88,-87.63],'Phoenix':[33.45,-112.07],'Miami':[25.76,-80.19],'Atlanta':[33.75,-84.39],'Boston':[42.36,-71.06],'Toronto':[43.65,-79.38],'Madrid':[40.42,-3.70],'Mexico City':[19.43,-99.13]};
let gS,gCam,gR,gG,gGr,gDr=false,gPr={x:0,y:0},gAR=true,gMk={},gRc,gMv,gPh=0;
function ll2v(la,lo,r){const p=(90-la)*Math.PI/180,t=(lo+180)*Math.PI/180;return new THREE.Vector3(-r*Math.sin(p)*Math.cos(t),r*Math.cos(p),r*Math.sin(p)*Math.sin(t))}
function initGlobe(){
  const wrap=$('gwrap');const W=wrap.offsetWidth||wrap.clientWidth||300;const H=wrap.offsetHeight||wrap.clientHeight||300;
  gS=new THREE.Scene();gCam=new THREE.PerspectiveCamera(40,W/H,.1,100);gCam.position.z=5.8;
  gR=new THREE.WebGLRenderer({canvas:$('gcanvas'),antialias:true,alpha:true});
  gR.setSize(W,H);gR.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  gS.add(new THREE.AmbientLight(0x0a1a3a,1));
  const dl1=new THREE.DirectionalLight(0x0055cc,1.2);dl1.position.set(6,4,6);gS.add(dl1);
  const dl2=new THREE.DirectionalLight(0x00aaff,.5);dl2.position.set(-4,-2,-4);gS.add(dl2);
  gG=new THREE.Mesh(new THREE.SphereGeometry(2,64,64),new THREE.MeshPhongMaterial({color:0x031320,emissive:0x010812,specular:0x004499,shininess:60}));gS.add(gG);
  gGr=new THREE.Mesh(new THREE.SphereGeometry(2.005,32,16),new THREE.MeshBasicMaterial({color:0x00d4ff,wireframe:true,transparent:true,opacity:.04}));gS.add(gGr);
  [0,Math.PI/2].forEach(rx=>{const m=new THREE.Mesh(new THREE.TorusGeometry(2.015,.002,8,128),new THREE.MeshBasicMaterial({color:0x00d4ff,transparent:true,opacity:.2}));m.rotation.x=rx;gS.add(m);});
  [[2.18,.1],[2.32,.04]].forEach(([r,o])=>{gS.add(new THREE.Mesh(new THREE.SphereGeometry(r,32,32),new THREE.MeshPhongMaterial({color:0x0033aa,emissive:0x001133,transparent:true,opacity:o,side:THREE.BackSide})));});
  const cv=$('gcanvas');
  cv.addEventListener('mousedown',e=>{gDr=true;gAR=false;gPr={x:e.clientX,y:e.clientY}});
  cv.addEventListener('mousemove',e=>{
    if(gDr){const dx=e.clientX-gPr.x,dy=e.clientY-gPr.y;gG.rotation.y+=dx*.004;gG.rotation.x+=dy*.004;gGr.rotation.copy(gG.rotation);gPr={x:e.clientX,y:e.clientY}}
    ghover(e,cv);
  });
  cv.addEventListener('mouseup',()=>gDr=false);
  cv.addEventListener('mouseleave',()=>{gDr=false;$('gtip').style.display='none'});
  cv.addEventListener('touchstart',e=>{gDr=true;gAR=false;gPr={x:e.touches[0].clientX,y:e.touches[0].clientY};},{passive:true});
  cv.addEventListener('touchmove',e=>{if(!gDr)return;const dx=e.touches[0].clientX-gPr.x,dy=e.touches[0].clientY-gPr.y;gG.rotation.y+=dx*.004;gG.rotation.x+=dy*.004;gGr.rotation.copy(gG.rotation);gPr={x:e.touches[0].clientX,y:e.touches[0].clientY};},{passive:true});
  cv.addEventListener('touchend',()=>gDr=false);
  window.addEventListener('resize',()=>{const nw=wrap.offsetWidth||wrap.clientWidth;const nh=wrap.offsetHeight||wrap.clientHeight;gCam.aspect=nw/nh;gCam.updateProjectionMatrix();gR.setSize(nw,nh)});
  ganimate();
}
function ghover(e,cv){
  if(!gRc){gRc=new THREE.Raycaster();gMv=new THREE.Vector2()}
  const rc=cv.getBoundingClientRect();gMv.x=((e.clientX-rc.left)/rc.width)*2-1;gMv.y=-((e.clientY-rc.top)/rc.height)*2+1;
  gRc.setFromCamera(gMv,gCam);
  const meshes=Object.values(gMk).flatMap(m=>m.hits||[]);
  const hits=gRc.intersectObjects(meshes);const tip=$('gtip');
  if(hits.length){
    const city=hits[0].object.userData.city;const s=(D.city_stats||{})[city]||{};
    const wr=s.wins+s.losses>0?Math.round(s.wins/(s.wins+s.losses)*100):null;
    tip.style.display='block';tip.style.left=(e.clientX-cv.getBoundingClientRect().left+14)+'px';tip.style.top=(e.clientY-cv.getBoundingClientRect().top-10)+'px';
    tip.innerHTML=`<strong>${city}</strong>
      <div class=\"gs\"><span>Wins</span><span style=\"color:var(--green)\">${s.wins||0}</span></div>
      <div class=\"gs\"><span>Losses</span><span style=\"color:var(--red)\">${s.losses||0}</span></div>
      ${s.open?`<div class=\"gs\"><span>Abertos</span><span style=\"color:var(--amber)\">${s.open}</span></div>`:''}
      <div class=\"gs\"><span>PnL</span><span style=\"color:${(s.pnl||0)>=0?'var(--green)':'var(--red)'}\">${(s.pnl||0)>=0?'+':''}$${Math.abs(s.pnl||0).toFixed(2)}</span></div>
      ${wr!==null?`<div class=\"gs\"><span>Win Rate</span><span style=\"color:var(--cyan)\">${wr}%</span></div>`:''}`;
  }else tip.style.display='none';
}
function ganimate(){requestAnimationFrame(ganimate);if(gAR){gG.rotation.y+=.0017;gGr.rotation.copy(gG.rotation);Object.values(gMk).forEach(m=>{if(m.pivot)m.pivot.rotation.y+=.0017})}
  gPh+=.04;Object.values(gMk).forEach(m=>{if(m.ring){const sc=1+.18*Math.sin(gPh+m.ph);m.ring.scale.set(sc,sc,sc);m.ring.material.opacity=.22+.18*Math.sin(gPh+m.ph)}if(m.halo)m.halo.material.opacity=.08+.06*Math.sin(gPh*.7+m.ph);if(m.beam)m.beam.material.opacity=.28+.18*Math.sin(gPh*1.3+m.ph);});gR.render(gS,gCam);}
function globe(){
  if(!gS){initGlobe();return}
  const cs=D.city_stats||{};
  Object.values(gMk).forEach(m=>{if(m.pivot)gS.remove(m.pivot)});gMk={};
  Object.entries(CC).forEach(([city,[la,lo]])=>{
    const s=cs[city];if(!s)return;
    const tot=s.wins+s.losses+s.open;if(!tot)return;
    const pos=ll2v(la,lo,2);const pnl=s.pnl||0;
    const col=pnl>5?0x00ff88:pnl>0?0x00d4ff:pnl<-2?0xff2d55:0xffb800;
    const sz=.04+Math.min(.1,tot*.006);
    const pivot=new THREE.Object3D();pivot.rotation.copy(gG.rotation);gS.add(pivot);
    const dot=new THREE.Mesh(new THREE.SphereGeometry(sz,10,10),new THREE.MeshPhongMaterial({color:col,emissive:col,emissiveIntensity:.7}));
    dot.position.copy(pos);dot.userData.city=city;pivot.add(dot);
    const bH=.1+sz*2;const bGeo=new THREE.CylinderGeometry(.002,.007,bH,6);
    const beam=new THREE.Mesh(bGeo,new THREE.MeshBasicMaterial({color:col,transparent:true,opacity:.4}));
    const bPos=pos.clone().multiplyScalar(1+bH/4);beam.position.copy(bPos);beam.lookAt(new THREE.Vector3(0,0,0));beam.rotateX(Math.PI/2);pivot.add(beam);
    const halo=new THREE.Mesh(new THREE.SphereGeometry(sz*2.5,10,10),new THREE.MeshBasicMaterial({color:col,transparent:true,opacity:.1,side:THREE.BackSide}));
    halo.position.copy(pos);pivot.add(halo);
    let ring=null;
    if(s.open>0){ring=new THREE.Mesh(new THREE.RingGeometry(sz*1.8,sz*2.4,24),new THREE.MeshBasicMaterial({color:0xffb800,side:THREE.DoubleSide,transparent:true,opacity:.35}));ring.position.copy(pos);ring.lookAt(new THREE.Vector3(0,0,0));pivot.add(ring);}
    gMk[city]={pivot,hits:[dot],ring,halo,beam,ph:Math.random()*Math.PI*2};
  });
}
window.addEventListener('load',()=>{setTimeout(()=>{if(D)globe();else initGlobe();},50)});
</script>
</body>
</html>""";


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def do_GET(self):
        if self.path == '/api/stats':
            try:
                data, warning = load_data()
                if data is None:
                    self.send_response(503); self.send_header('Content-Type','application/json'); self.end_headers()
                    self.wfile.write(json.dumps({"error": warning}).encode()); return
                stats = build_stats(data)
                warns = []
                if warning: warns.append(warning)
                div = stats.get("balance_divergence") or 0
                if abs(div) > 0.05: warns.append(f"\u26a0 Diverg\u00eancia de saldo: ${div:+.2f}")
                if warns: stats["warning"] = " | ".join(warns)
                body = json.dumps(stats, ensure_ascii=False).encode('utf-8')
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length', len(body)); self.end_headers(); self.wfile.write(body)
            except Exception as e:
                err = json.dumps({"error": str(e)}).encode()
                self.send_response(500); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(err)
        elif self.path in ('/', '/index.html'):
            body = HTML.encode('utf-8', errors='replace')
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length', len(body)); self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()


if __name__ == '__main__':
    print(f'Dashboard rodando em http://0.0.0.0:{PORT}')
    try:
        ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\nEncerrado')
