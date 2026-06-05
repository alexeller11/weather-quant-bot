"""
DASHBOARD — WEATHER QUANT BOT
Dashboard de última geração: globo 3D, gráficos interativos, filtros em tempo real.
"""

import os, json, base64
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("PORT", 8765))

# ── Carrega dados ─────────────────────────────────────────────────────────────

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
            if row:
                return row[0], None
            errors.append("PostgreSQL: sem registros")
        except Exception as e:
            errors.append(f"PostgreSQL: {str(e)[:80]}")
    else:
        errors.append("DATABASE_URL não configurada")

    try:
        token  = os.environ.get("GITHUB_TOKEN", "").strip()
        repo   = os.environ.get("GITHUB_REPO", "").strip()
        branch = os.environ.get("GITHUB_BRANCH", "main")
        if token and repo:
            import requests as req
            r = req.get(
                f"https://api.github.com/repos/{repo}/contents/bankroll.json",
                headers={"Authorization": f"token {token}"},
                params={"ref": branch}, timeout=10,
            )
            if r.status_code == 200:
                data = json.loads(base64.b64decode(r.json()["content"]).decode())
                return data, "⚠ Dados do GitHub (PostgreSQL indisponível)"
            errors.append(f"GitHub HTTP {r.status_code}")
        else:
            errors.append("GITHUB_TOKEN/REPO não configurados")
    except Exception as e:
        errors.append(f"GitHub: {str(e)[:80]}")

    return None, " | ".join(errors)


def _max_drawdown(equity_series):
    if not equity_series:
        return 0.0
    peak = equity_series[0]
    mdd  = 0.0
    for v in equity_series:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        mdd = max(mdd, dd)
    return round(mdd * 100, 2)


def _drawdown_series(equity_series):
    if not equity_series:
        return []
    peak = equity_series[0]
    out  = []
    for v in equity_series:
        if v > peak:
            peak = v
        dd = round((peak - v) / peak * 100, 2) if peak > 0 else 0
        out.append(dd)
    return out


def _sharpe(closed):
    if len(closed) < 2:
        return None
    import math
    returns = [float(t.get("pnl") or 0) / float(t.get("stake") or 1) for t in closed]
    mu  = sum(returns) / len(returns)
    var = sum((r - mu) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0
    return round(mu / std, 3) if std > 0 else None


def _profit_factor(wins, losses_list):
    gross_win  = sum(float(t.get("pnl") or 0) for t in wins)
    gross_loss = sum(abs(float(t.get("pnl") or 0)) for t in losses_list)
    if gross_loss == 0:
        return None
    return round(gross_win / gross_loss, 3)


def _calibration_bins(closed, n_bins=5):
    from collections import defaultdict
    bins = defaultdict(list)
    for t in closed:
        prob = t.get("model_prob")
        if prob is None:
            continue
        b = min(int(float(prob) * n_bins), n_bins - 1)
        bins[b].append(1.0 if t.get("result") == "WIN" else 0.0)
    result = []
    for b in range(n_bins):
        lo = b / n_bins * 100
        hi = (b + 1) / n_bins * 100
        mid = (lo + hi) / 2
        outcomes = bins.get(b, [])
        wr = round(sum(outcomes) / len(outcomes) * 100, 1) if outcomes else None
        result.append({"label": f"{lo:.0f}–{hi:.0f}%", "predicted": mid, "actual": wr, "n": len(outcomes)})
    return result


def _rolling_winrate(closed, window=10):
    if len(closed) < window:
        return None
    recent = closed[-window:]
    return round(sum(1 for t in recent if t.get("result") == "WIN") / window * 100, 1)


def build_stats(data):
    history  = data.get("history", [])
    balance  = data.get("balance", 0)
    start    = data.get("start_balance", 50)
    closed   = sorted(
        [t for t in history if t.get("result") in ("WIN","LOSS")],
        key=lambda x: x.get("exit_time","") or ""
    )
    open_t   = [t for t in history if t.get("result") == "OPEN"]
    wins     = [t for t in closed  if t.get("result") == "WIN"]
    losses   = [t for t in closed  if t.get("result") == "LOSS"]
    pnl      = sum(float(t.get("pnl") or 0) for t in closed)
    exposure = sum(float(t.get("stake") or 0) for t in open_t)
    win_rate = round(len(wins)/len(closed)*100,1) if closed else 0

    city_stats = {}
    for t in history:
        c = t.get("city","?")
        if c not in city_stats:
            city_stats[c] = {"wins":0,"losses":0,"pnl":0,"stake":0,"open":0,"open_stake":0}
        if t.get("result") == "WIN":
            city_stats[c]["wins"] += 1
            city_stats[c]["pnl"]  += float(t.get("pnl") or 0)
        elif t.get("result") == "LOSS":
            city_stats[c]["losses"] += 1
            city_stats[c]["pnl"]    += float(t.get("pnl") or 0)
        elif t.get("result") == "OPEN":
            city_stats[c]["open"]       += 1
            city_stats[c]["open_stake"] += float(t.get("stake") or 0)
        city_stats[c]["stake"] += float(t.get("stake") or 0)

    # Por tipo (ABOVE / BELOW / EXACT)
    type_stats = {}
    for t in closed:
        tp = (t.get("type") or "?").upper()
        if tp not in type_stats:
            type_stats[tp] = {"wins":0,"losses":0,"pnl":0.0}
        if t.get("result") == "WIN":
            type_stats[tp]["wins"] += 1
        else:
            type_stats[tp]["losses"] += 1
        type_stats[tp]["pnl"] += float(t.get("pnl") or 0)

    # Equity curve + drawdown
    equity_curve = []
    running = float(start)
    eq_vals = [running]
    for t in closed:
        running += float(t.get("pnl") or 0)
        eq_vals.append(round(running, 2))
        equity_curve.append({
            "date":    (t.get("exit_time","") or "")[:10],
            "balance": round(running, 2),
            "result":  t.get("result",""),
            "city":    t.get("city",""),
        })

    dd_series = _drawdown_series(eq_vals)
    mdd       = _max_drawdown(eq_vals)

    brier_scores = []
    for _t in closed:
        if _t.get("model_prob") is None:
            continue
        _prob_yes = float(_t.get("model_prob") or 0)
        _side = (_t.get("side") or "YES").upper()
        _outcome = 1.0 if _t.get("result") == "WIN" else 0.0
        # Para NO: probabilidade apostada é prob_no = 1 - prob_yes
        _prob_aposta = (1.0 - _prob_yes) if _side == "NO" else _prob_yes
        brier_scores.append((_prob_aposta - _outcome) ** 2)
    brier = round(sum(brier_scores)/len(brier_scores),4) if brier_scores else None

    avg_edge = round(sum(float(t.get("edge") or 0) for t in history)/len(history)*100,2) if history else 0

    # Rolling win rate (last 10)
    wr10 = _rolling_winrate(closed, 10)

    return {
        "balance":        round(float(balance),2),
        "start_balance":  round(float(start),2),
        "pnl":            round(pnl,2),
        "win_rate":       win_rate,
        "win_rate_10":    wr10,
        "total_closed":   len(closed),
        "wins":           len(wins),
        "losses":         len(losses),
        "open_count":     len(open_t),
        "exposure":       round(exposure,2),
        "brier":          brier,
        "avg_edge":       avg_edge,
        "max_drawdown":   mdd,
        "profit_factor":  _profit_factor(wins, losses),
        "sharpe":         _sharpe(closed),
        "city_stats":     city_stats,
        "type_stats":     type_stats,
        "equity_curve":   equity_curve,
        "drawdown_curve": [
            {"date": equity_curve[i]["date"], "dd": dd_series[i+1]}
            for i in range(len(equity_curve))
        ],
        "calibration":    _calibration_bins(closed),
        "open_trades":    open_t,
        "closed_trades":  list(reversed(closed))[:50],
        "all_trades":     history,
        "updated":        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weather Quant — Mission Control</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<style>
:root{
  --bg:#030b18;--bg1:#060f22;--bg2:#091529;--bg3:#0d1d36;
  --cyan:#00e5ff;--green:#00ff88;--red:#ff3366;--amber:#ffaa00;--purple:#b66cff;
  --text:#cce8ff;--muted:#4a7090;--border:rgba(0,200,255,0.08);
  --card:rgba(6,18,38,0.85);
  --font-mono:'JetBrains Mono',monospace;
  --font-display:'Syne',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{background:var(--bg);color:var(--text);font-family:var(--font-mono);font-size:13px;overflow-x:hidden}
body{min-height:100vh}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:var(--bg1)}
::-webkit-scrollbar-thumb{background:var(--muted);border-radius:2px}
.stars{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.stars span{position:absolute;border-radius:50%;background:#fff;animation:twinkle var(--d,3s) var(--dl,0s) infinite alternate}
@keyframes twinkle{from{opacity:.1}to{opacity:.7}}
.wrapper{position:relative;z-index:1;max-width:1600px;margin:0 auto;padding:20px 24px}
header{display:flex;align-items:center;justify-content:space-between;padding:0 0 20px;border-bottom:1px solid var(--border)}
.logo{font-family:var(--font-display);font-size:22px;font-weight:800;letter-spacing:-.5px;color:#fff}
.logo span{color:var(--cyan)}
.hdr-right{display:flex;align-items:center;gap:16px}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.ts{color:var(--muted);font-size:11px}
.refresh-btn{background:transparent;border:1px solid var(--border);color:var(--muted);padding:6px 14px;border-radius:4px;cursor:pointer;font-family:var(--font-mono);font-size:11px;transition:.2s}
.refresh-btn:hover{border-color:var(--cyan);color:var(--cyan)}
.info-bar{display:flex;gap:20px;align-items:center;padding:8px 16px;background:rgba(0,200,255,.04);border:1px solid var(--border);border-radius:6px;margin-bottom:12px;flex-wrap:wrap}
.info-item{font-size:11px;color:var(--muted)}.info-item strong{color:var(--text)}
.kpi-row{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px 16px;position:relative;overflow:hidden;transition:.3s}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--accent,var(--cyan));border-radius:8px 8px 0 0}
.kpi:hover{border-color:var(--accent,var(--cyan));transform:translateY(-2px)}
.kpi-label{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:8px}
.kpi-value{font-family:var(--font-display);font-size:26px;font-weight:800;color:#fff;line-height:1}
.kpi-sub{font-size:10px;color:var(--muted);margin-top:6px}
.kpi-bar{position:absolute;bottom:0;left:0;height:2px;background:var(--accent,var(--cyan));opacity:.3;transition:width .8s}
.main-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:18px;backdrop-filter:blur(12px)}
.card-title{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:14px;display:flex;align-items:center;gap:8px}
.card-title::before{content:'';width:3px;height:12px;background:var(--cyan);border-radius:2px;flex-shrink:0}
#globe-wrap{position:relative;height:320px;cursor:grab;user-select:none}
#globe-wrap:active{cursor:grabbing}
#globe-canvas{width:100%;height:100%;display:block}
.globe-tooltip{position:absolute;background:rgba(4,12,28,.95);border:1px solid var(--cyan);border-radius:6px;padding:10px 14px;font-size:11px;pointer-events:none;display:none;z-index:10;min-width:140px}
.globe-tooltip strong{color:var(--cyan);display:block;margin-bottom:4px;font-size:12px}
.chart-wrap{position:relative;height:280px}
.filter-bar{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px 18px;margin-bottom:16px;display:flex;align-items:center;gap:20px;flex-wrap:wrap}
.filter-label{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}
.city-chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{background:rgba(0,200,255,.06);border:1px solid var(--border);border-radius:20px;padding:4px 12px;font-size:11px;cursor:pointer;transition:.2s;color:var(--muted)}
.chip:hover{border-color:var(--cyan);color:var(--cyan)}
.chip.active{background:rgba(0,229,255,.12);border-color:var(--cyan);color:var(--cyan)}
.result-btns{display:flex;gap:4px}
.rbtn{background:transparent;border:1px solid var(--border);border-radius:4px;padding:4px 12px;font-family:var(--font-mono);font-size:11px;color:var(--muted);cursor:pointer;transition:.2s}
.rbtn:hover{border-color:var(--cyan)}
.rbtn.on{background:rgba(0,229,255,.1);border-color:var(--cyan);color:var(--cyan)}
.rbtn.on-win{background:rgba(0,255,136,.1);border-color:var(--green);color:var(--green)}
.rbtn.on-loss{background:rgba(255,51,102,.1);border-color:var(--red);color:var(--red)}
.charts-row{display:grid;grid-template-columns:2fr 1fr 1fr;gap:16px;margin-bottom:16px}
.charts-row2{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px}
.table-card{background:var(--card);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}
.table-header{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.tbl-wrap{max-height:380px;overflow-y:auto}
table{width:100%;border-collapse:collapse}
th{padding:10px 14px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg2);z-index:1}
td{padding:9px 14px;border-bottom:1px solid rgba(0,200,255,.04);font-size:12px}
tr:hover td{background:rgba(0,200,255,.03)}
.city-tag{display:inline-block;padding:2px 8px;border-radius:12px;background:rgba(0,200,255,.08);color:var(--cyan);font-size:10px}
.badge-win{color:var(--green)}
.badge-loss{color:var(--red)}
.badge-open{color:var(--amber)}
.prob-bar-row{display:flex;align-items:center;gap:6px}
.prob-bar-bg{flex:1;height:3px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden}
.prob-bar-fill{height:100%;border-radius:2px;background:var(--cyan)}
.edge-pos{color:var(--green)}
.edge-neg{color:var(--red)}
.gauge-wrap{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%}
.gauge-val{font-family:var(--font-display);font-size:36px;font-weight:800;color:#fff;margin-top:-20px}
.gauge-sub{font-size:11px;color:var(--muted);margin-top:4px}
.empty{color:var(--muted);text-align:center;padding:40px;font-size:12px}
.warning-bar{background:rgba(255,170,0,.08);border-bottom:1px solid rgba(255,170,0,.2);padding:8px 24px;font-size:11px;color:var(--amber)}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.card,.kpi,.table-card{animation:fadeUp .4s ease both}
.kpi:nth-child(1){animation-delay:.05s}
.kpi:nth-child(2){animation-delay:.1s}
.kpi:nth-child(3){animation-delay:.15s}
.kpi:nth-child(4){animation-delay:.2s}
.kpi:nth-child(5){animation-delay:.25s}
.kpi:nth-child(6){animation-delay:.3s}
</style>
</head>
<body>
<div class="stars" id="stars"></div>
<div id="warning-bar" style="display:none" class="warning-bar"></div>
<div class="wrapper">
  <header>
    <div class="logo">⚡ Weather<span>Quant</span></div>
    <div class="hdr-right">
      <div class="status-dot" id="statusDot"></div>
      <span class="ts" id="tsLabel">—</span>
      <button class="refresh-btn" onclick="fetchData()">↻ Atualizar</button>
    </div>
  </header>
  <div class="info-bar" id="infoBar">
    <div class="info-item">Abertos: <strong id="iOpen">—</strong></div>
    <div class="info-item">Exposição: <strong id="iExp">—</strong></div>
    <div class="info-item">Edge médio: <strong id="iEdge">—</strong></div>
    <div class="info-item">Brier score: <strong id="iBrier">—</strong></div>
    <div class="info-item">WR últimos 10: <strong id="iWR10">—</strong></div>
  </div>
  <div class="kpi-row" id="kpiRow">
    <div class="kpi" style="--accent:var(--cyan)">
      <div class="kpi-label">Saldo</div>
      <div class="kpi-value" id="kBalance">—</div>
      <div class="kpi-sub" id="kBalanceSub">—</div>
      <div class="kpi-bar" id="kBalanceBar" style="width:0"></div>
    </div>
    <div class="kpi" style="--accent:var(--green)">
      <div class="kpi-label">PnL Total</div>
      <div class="kpi-value" id="kPnl">—</div>
      <div class="kpi-sub" id="kPnlSub">—</div>
    </div>
    <div class="kpi" style="--accent:var(--purple)">
      <div class="kpi-label">Win Rate</div>
      <div class="kpi-value" id="kWR">—</div>
      <div class="kpi-sub" id="kWRSub">—</div>
    </div>
    <div class="kpi" style="--accent:var(--amber)">
      <div class="kpi-label">Profit Factor</div>
      <div class="kpi-value" id="kPF">—</div>
      <div class="kpi-sub" id="kPFSub">>1 = rentável</div>
    </div>
    <div class="kpi" style="--accent:var(--red)">
      <div class="kpi-label">Max Drawdown</div>
      <div class="kpi-value" id="kMDD">—</div>
      <div class="kpi-sub" id="kMDDSub">queda máx do pico</div>
    </div>
    <div class="kpi" style="--accent:#4fc3f7">
      <div class="kpi-label">Sharpe Ratio</div>
      <div class="kpi-value" id="kSharpe">—</div>
      <div class="kpi-sub" id="kSharpeSub">>1 = bom</div>
    </div>
  </div>
  <div class="main-grid">
    <div class="card">
      <div class="card-title">🌍 Globo de Trades — arraste para girar</div>
      <div id="globe-wrap">
        <canvas id="globe-canvas"></canvas>
        <div class="globe-tooltip" id="globeTip"></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">📈 Curva de Equity</div>
      <div class="chart-wrap"><canvas id="equityChart"></canvas></div>
    </div>
  </div>
  <div class="filter-bar">
    <span class="filter-label">Cidade</span>
    <div class="city-chips" id="cityChips"></div>
    <span class="filter-label" style="margin-left:8px">Resultado</span>
    <div class="result-btns">
      <button class="rbtn on" data-r="all" onclick="setResult(this,'all')">Todos</button>
      <button class="rbtn" data-r="OPEN" onclick="setResult(this,'OPEN')">Abertos</button>
      <button class="rbtn" data-r="WIN" onclick="setResult(this,'WIN')">Win</button>
      <button class="rbtn" data-r="LOSS" onclick="setResult(this,'LOSS')">Loss</button>
    </div>
  </div>
  <div class="charts-row">
    <div class="card">
      <div class="card-title">💰 PnL por Cidade</div>
      <div class="chart-wrap" style="height:220px"><canvas id="cityChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">🎯 Distribuição de Edge</div>
      <div class="chart-wrap" style="height:220px"><canvas id="edgeChart"></canvas></div>
    </div>
    <div class="card" style="display:flex;flex-direction:column">
      <div class="card-title">🏆 Win Rate</div>
      <div class="gauge-wrap">
        <canvas id="gaugeChart" width="160" height="90"></canvas>
        <div class="gauge-val" id="gaugeVal">—</div>
        <div class="gauge-sub" id="gaugeSub">—</div>
      </div>
    </div>
  </div>
  <div class="charts-row2">
    <div class="card">
      <div class="card-title">📉 Drawdown (%)</div>
      <div class="chart-wrap" style="height:180px"><canvas id="ddChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">🔬 Calibração do Modelo</div>
      <div class="chart-wrap" style="height:180px"><canvas id="calChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">⚡ PnL por Tipo de Mercado</div>
      <div class="chart-wrap" style="height:180px"><canvas id="typeChart"></canvas></div>
    </div>
  </div>
  <div class="table-card">
    <div class="table-header">
      <div class="card-title" style="margin:0">⏳ Posições Abertas</div>
      <span id="openCount" style="color:var(--amber);font-size:12px"></span>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th>Cidade</th><th>Data</th><th>Side</th><th>Tipo</th><th>Stake</th>
          <th>Prob Aposta</th><th>Entry</th><th>Edge</th><th>Pergunta</th>
        </tr></thead>
        <tbody id="openBody"></tbody>
      </table>
    </div>
  </div>
  <div class="table-card">
    <div class="table-header">
      <div class="card-title" style="margin:0">📋 Trades Fechados</div>
      <span id="closedCount" style="color:var(--muted);font-size:12px"></span>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th></th><th>Cidade</th><th>Data</th><th>Side</th><th>Target</th>
          <th>Stake</th><th>PnL</th><th>Prob</th><th>Entry</th><th>Temp Real</th>
        </tr></thead>
        <tbody id="closedBody"></tbody>
      </table>
    </div>
  </div>
</div>
<script>
(function(){
  const c=document.getElementById('stars');
  for(let i=0;i<120;i++){
    const s=document.createElement('span');
    const sz=Math.random()*2+.5;
    s.style.cssText=`width:${sz}px;height:${sz}px;top:${Math.random()*100}%;left:${Math.random()*100}%;--d:${2+Math.random()*4}s;--dl:${Math.random()*4}s`;
    c.appendChild(s);
  }
})();

let DATA=null,activeCity='all',activeResult='all';
let chartEquity=null,chartCity=null,chartEdge=null,chartDD=null,chartCal=null,chartType=null;

async function fetchData(){
  try{
    const r=await fetch('/api/stats');
    if(!r.ok)throw new Error(r.status);
    DATA=await r.json();
    render();
  }catch(e){console.error(e)}
}
fetchData();
setInterval(fetchData,15000);

function render(){
  if(!DATA)return;
  updateKPIs();
  buildCityChips();
  updateEquity();
  updateCityChart();
  updateEdgeChart();
  updateGauge();
  updateDrawdown();
  updateCalibration();
  updateTypeChart();
  updateTables();
  updateGlobe();
  document.getElementById('tsLabel').textContent=DATA.updated||'';
  const wb=document.getElementById('warning-bar');
  if(DATA.warning){wb.style.display='block';wb.textContent=DATA.warning}else{wb.style.display='none'}
}

function sign(v){return v>=0?'+':''}

function updateKPIs(){
  const d=DATA;
  const pnlPct=d.start_balance>0?((d.balance-d.start_balance)/d.start_balance*100).toFixed(1):0;

  // Saldo
  document.getElementById('kBalance').textContent='$'+d.balance.toFixed(2);
  document.getElementById('kBalanceSub').textContent=sign(d.balance-d.start_balance)+'$'+(d.balance-d.start_balance).toFixed(2)+' vs início';
  const barW=Math.min(100,Math.max(0,(d.balance/d.start_balance)*100));
  document.getElementById('kBalanceBar').style.width=barW+'%';

  // PnL
  const pnlEl=document.getElementById('kPnl');
  pnlEl.textContent=sign(d.pnl)+'$'+Math.abs(d.pnl).toFixed(2);
  pnlEl.style.color=d.pnl>=0?'var(--green)':'var(--red)';
  document.getElementById('kPnlSub').textContent=sign(parseFloat(pnlPct))+pnlPct+'% retorno';

  // Win Rate
  document.getElementById('kWR').textContent=d.win_rate+'%';
  document.getElementById('kWRSub').textContent=d.wins+'W / '+d.losses+'L ('+d.total_closed+' trades)';

  // Profit Factor
  const pfEl=document.getElementById('kPF');
  if(d.profit_factor!==null&&d.profit_factor!==undefined){
    pfEl.textContent=d.profit_factor.toFixed(2)+'×';
    pfEl.style.color=d.profit_factor>=1.5?'var(--green)':d.profit_factor>=1.0?'var(--amber)':'var(--red)';
  }else{pfEl.textContent='N/A';pfEl.style.color='var(--muted)'}

  // Max Drawdown
  const mddEl=document.getElementById('kMDD');
  mddEl.textContent=(d.max_drawdown||0).toFixed(1)+'%';
  mddEl.style.color=d.max_drawdown>50?'var(--red)':d.max_drawdown>25?'var(--amber)':'var(--green)';

  // Sharpe
  const shrEl=document.getElementById('kSharpe');
  if(d.sharpe!==null&&d.sharpe!==undefined){
    shrEl.textContent=d.sharpe.toFixed(2);
    shrEl.style.color=d.sharpe>=1?'var(--green)':d.sharpe>=0?'var(--amber)':'var(--red)';
  }else{shrEl.textContent='N/A';shrEl.style.color='var(--muted)'}

  // Info bar
  document.getElementById('iOpen').textContent=d.open_count+' ($'+d.exposure.toFixed(2)+')';
  document.getElementById('iEdge').textContent=sign(d.avg_edge)+d.avg_edge.toFixed(1)+'%';
  document.getElementById('iBrier').textContent=d.brier!==null&&d.brier!==undefined?d.brier:'N/A';
  document.getElementById('iWR10').textContent=d.win_rate_10!==null&&d.win_rate_10!==undefined?d.win_rate_10+'%':'N/A';
  const wr10El=document.getElementById('iWR10');
  if(d.win_rate_10!==null&&d.win_rate_10!==undefined){
    wr10El.textContent=d.win_rate_10+'%';
    wr10El.style.color=d.win_rate_10>=55?'var(--green)':d.win_rate_10>=45?'var(--amber)':'var(--red)';
  }
}

function buildCityChips(){
  const wrap=document.getElementById('cityChips');
  const cities=['all',...Object.keys(DATA.city_stats)];
  const existing=new Set([...wrap.querySelectorAll('.chip')].map(c=>c.dataset.c));
  if(JSON.stringify([...existing])==JSON.stringify(cities))return;
  wrap.innerHTML='';
  cities.forEach(c=>{
    const chip=document.createElement('button');
    chip.className='chip'+(c===activeCity?' active':'');
    chip.dataset.c=c;
    chip.textContent=c==='all'?'Todas':c;
    chip.onclick=()=>{activeCity=c;[...wrap.querySelectorAll('.chip')].forEach(x=>x.classList.remove('active'));chip.classList.add('active');updateCityChart();updateTables()};
    wrap.appendChild(chip);
  });
}

function setResult(el,r){
  activeResult=r;
  document.querySelectorAll('.rbtn').forEach(b=>{b.className='rbtn'});
  el.className='rbtn '+(r==='all'?'on':r==='WIN'?'on-win':'on-loss');
  updateTables();
}

function filteredClosed(){
  return DATA.closed_trades.filter(t=>{
    if(activeCity!=='all'&&t.city!==activeCity)return false;
    if(activeResult==='all'||activeResult==='OPEN')return true;
    return t.result===activeResult;
  });
}
function filteredOpen(){
  return DATA.open_trades.filter(t=>activeCity==='all'||t.city===activeCity);
}

function updateEquity(){
  const eq=DATA.equity_curve;
  const ctx=document.getElementById('equityChart').getContext('2d');
  const labels=eq.map(p=>p.date);
  const vals=eq.map(p=>p.balance);
  if(chartEquity)chartEquity.destroy();
  const grad=ctx.createLinearGradient(0,0,0,280);
  grad.addColorStop(0,'rgba(0,229,255,.25)');
  grad.addColorStop(1,'rgba(0,229,255,0)');
  chartEquity=new Chart(ctx,{
    type:'line',
    data:{labels,datasets:[{data:vals,borderColor:'#00e5ff',backgroundColor:grad,fill:true,tension:.4,
      pointRadius:vals.map((_,i)=>i===vals.length-1?5:3),
      pointBackgroundColor:eq.map(p=>p.result==='WIN'?'#00ff88':'#ff3366'),
      pointBorderColor:'#030b18',pointBorderWidth:2}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>' $'+c.parsed.y.toFixed(2)}}},
      scales:{
        x:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:10},maxRotation:0,autoSkip:true,maxTicksLimit:8}},
        y:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:10},callback:v=>'$'+v.toFixed(0)}}
      }}
  });
}

function updateCityChart(){
  const cs=DATA.city_stats;
  let entries=Object.entries(cs).filter(([c])=>activeCity==='all'||c===activeCity);
  entries.sort((a,b)=>b[1].pnl-a[1].pnl);
  const labels=entries.map(e=>e[0]);
  const vals=entries.map(e=>e[1].pnl);
  const colors=vals.map(v=>v>=0?'rgba(0,255,136,.7)':'rgba(255,51,102,.7)');
  const borders=vals.map(v=>v>=0?'#00ff88':'#ff3366');
  const ctx=document.getElementById('cityChart').getContext('2d');
  if(chartCity)chartCity.destroy();
  chartCity=new Chart(ctx,{
    type:'bar',
    data:{labels,datasets:[{data:vals,backgroundColor:colors,borderColor:borders,borderWidth:1,borderRadius:4}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` $${c.parsed.x.toFixed(2)}`}}},
      scales:{
        x:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:10},callback:v=>'$'+v.toFixed(0)}},
        y:{grid:{display:false},ticks:{color:'#cce8ff',font:{size:11}}}
      }}
  });
}

function updateEdgeChart(){
  const edges=DATA.all_trades.filter(t=>t.edge!=null).map(t=>Math.round(t.edge*100));
  const buckets={};
  edges.forEach(e=>{const b=Math.floor(e/5)*5;buckets[b]=(buckets[b]||0)+1});
  const keys=Object.keys(buckets).sort((a,b)=>a-b);
  const ctx=document.getElementById('edgeChart').getContext('2d');
  if(chartEdge)chartEdge.destroy();
  chartEdge=new Chart(ctx,{
    type:'bar',
    data:{labels:keys.map(k=>k+'%'),datasets:[{data:keys.map(k=>buckets[k]),backgroundColor:'rgba(182,108,255,.6)',borderColor:'#b66cff',borderWidth:1,borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false}},
      scales:{
        x:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:10}}},
        y:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:10}}}
      }}
  });
}

function updateGauge(){
  const wr=DATA.win_rate/100;
  const c=document.getElementById('gaugeChart');
  const ctx=c.getContext('2d');
  ctx.clearRect(0,0,160,90);
  const cx=80,cy=80,r=65,start=Math.PI,end=2*Math.PI;
  ctx.beginPath();ctx.arc(cx,cy,r,start,end);
  ctx.strokeStyle='rgba(255,255,255,.06)';ctx.lineWidth=12;ctx.lineCap='round';ctx.stroke();
  const col=wr>=.55?'#00ff88':wr>=.45?'#ffaa00':'#ff3366';
  ctx.beginPath();ctx.arc(cx,cy,r,start,start+(end-start)*wr);
  ctx.strokeStyle=col;ctx.lineWidth=12;ctx.lineCap='round';ctx.stroke();
  document.getElementById('gaugeVal').textContent=DATA.win_rate+'%';
  document.getElementById('gaugeVal').style.color=col;
  document.getElementById('gaugeSub').textContent=DATA.wins+'W / '+DATA.losses+'L';
}

function updateTables(){
  const open=filteredOpen();
  document.getElementById('openCount').textContent=open.length+' posições';
  const ob=document.getElementById('openBody');
  if(!open.length){ob.innerHTML='<tr><td colspan="8" class="empty">Nenhuma posição aberta</td></tr>';return}
  ob.innerHTML=open.map(t=>{
    const side=t.side||'YES';
    const probAposta=side==='NO'?Math.round((1-(t.model_prob||0))*100):Math.round((t.model_prob||0)*100);
    const entryPct=Math.round((t.entry_price||t.market_price||0)*100);
    const edge=((t.edge||0)*100).toFixed(1);
    const cls=parseFloat(edge)>=0?'edge-pos':'edge-neg';
    const sideClr=side==='NO'?'var(--amber)':'var(--cyan)';
    return`<tr>
      <td><span class="city-tag">${t.city||'—'}</span></td>
      <td>${t.market_date||'—'}</td>
      <td><b style="color:${sideClr}">${side}</b></td>
      <td style="color:var(--amber)">${t.type||'—'}</td>
      <td>$${(t.stake||0).toFixed(2)}</td>
      <td><div class="prob-bar-row"><div class="prob-bar-bg"><div class="prob-bar-fill" style="width:${probAposta}%"></div></div><span>${probAposta}%</span></div></td>
      <td>${entryPct}%</td>
      <td class="${cls}">${parseFloat(edge)>=0?'+':''}${edge}%</td>
      <td style="color:var(--muted);font-size:11px">${(t.question||'').substring(0,50)}…</td>
    </tr>`}).join('');

  const closed=filteredClosed();
  document.getElementById('closedCount').textContent=closed.length+' trades';
  const cb=document.getElementById('closedBody');
  if(!closed.length){cb.innerHTML='<tr><td colspan="9" class="empty">Nenhum trade fechado</td></tr>';return}
  cb.innerHTML=closed.map(t=>{
    const isWin=t.result==='WIN';
    const pnl=t.pnl||0;
    const temp=t.real_temp_c!=null?t.real_temp_c.toFixed(1)+'°C':'—';
    const side=t.side||'YES';
    const probAposta=side==='NO'?Math.round((1-(t.model_prob||0))*100):Math.round((t.model_prob||0)*100);
    const entryPct=Math.round((t.entry_price||t.market_price||0)*100);
    const sideClr=side==='NO'?'var(--amber)':'var(--cyan)';
    return`<tr>
      <td class="${isWin?'badge-win':'badge-loss'}" style="font-size:15px">${isWin?'✓':'✗'}</td>
      <td><span class="city-tag">${t.city||'—'}</span></td>
      <td>${t.market_date||'—'}</td>
      <td><b style="color:${sideClr}">${side}</b></td>
      <td style="color:var(--muted)">${t.type||''} ${t.target||''}°${t.unit||'C'}</td>
      <td>$${(t.stake||0).toFixed(2)}</td>
      <td class="${pnl>=0?'badge-win':'badge-loss'}" style="font-weight:600">${pnl>=0?'+':''}$${Math.abs(pnl).toFixed(2)}</td>
      <td>${probAposta}%</td>
      <td>${entryPct}%</td>
      <td style="color:var(--cyan)">${temp}</td>
    </tr>`}).join('');
}

function updateDrawdown(){
  const dc=DATA.drawdown_curve||[];
  const labels=dc.map(p=>p.date);
  const vals=dc.map(p=>p.dd);
  const ctx=document.getElementById('ddChart').getContext('2d');
  if(chartDD)chartDD.destroy();
  const grad=ctx.createLinearGradient(0,0,0,180);
  grad.addColorStop(0,'rgba(255,51,102,.35)');
  grad.addColorStop(1,'rgba(255,51,102,0)');
  chartDD=new Chart(ctx,{
    type:'line',
    data:{labels,datasets:[{data:vals,borderColor:'#ff3366',backgroundColor:grad,fill:true,tension:.3,
      pointRadius:0,borderWidth:1.5}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.parsed.y.toFixed(1)}%`}}},
      scales:{
        x:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:9},maxTicksLimit:6,maxRotation:0}},
        y:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:9},callback:v=>v+'%'},reverse:true}
      }}
  });
}

function updateCalibration(){
  const cal=DATA.calibration||[];
  const labels=cal.map(b=>b.label);
  const predicted=cal.map(b=>b.predicted);
  const actual=cal.map(b=>b.actual);
  const ctx=document.getElementById('calChart').getContext('2d');
  if(chartCal)chartCal.destroy();
  chartCal=new Chart(ctx,{
    type:'bar',
    data:{labels,datasets:[
      {label:'Modelo previu',data:predicted,backgroundColor:'rgba(0,229,255,.25)',borderColor:'#00e5ff',borderWidth:1,borderRadius:3},
      {label:'Win rate real',data:actual,backgroundColor:'rgba(0,255,136,.5)',borderColor:'#00ff88',borderWidth:1,borderRadius:3},
    ]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{
        legend:{display:true,labels:{color:'#4a7090',font:{size:9},boxWidth:10}},
        tooltip:{callbacks:{label:c=>` ${c.dataset.label}: ${c.parsed.y!==null?c.parsed.y.toFixed(1)+'%':'N/A'}`}},
      },
      scales:{
        x:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:9}}},
        y:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:9},callback:v=>v+'%'},min:0,max:100}
      }}
  });
}

function updateTypeChart(){
  const ts=DATA.type_stats||{};
  const types=Object.keys(ts);
  if(!types.length){document.getElementById('typeChart').style.display='none';return}
  const pnls=types.map(t=>ts[t].pnl||0);
  const wrs=types.map(t=>{const n=ts[t].wins+ts[t].losses;return n?Math.round(ts[t].wins/n*100):0});
  const colors=pnls.map(v=>v>=0?'rgba(0,255,136,.7)':'rgba(255,51,102,.7)');
  const ctx=document.getElementById('typeChart').getContext('2d');
  if(chartType)chartType.destroy();
  chartType=new Chart(ctx,{
    type:'bar',
    data:{
      labels:types.map(t=>{const n=ts[t].wins+ts[t].losses;return `${t} (${wrs[types.indexOf(t)]}% WR)`}),
      datasets:[{label:'PnL',data:pnls,backgroundColor:colors,borderColor:colors.map(c=>c.replace('.7','.9')),borderWidth:1,borderRadius:4}]
    },
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` PnL: $${c.parsed.y.toFixed(2)}`}}},
      scales:{
        x:{grid:{display:false},ticks:{color:'#cce8ff',font:{size:10}}},
        y:{grid:{color:'rgba(0,200,255,.04)'},ticks:{color:'#4a7090',font:{size:9},callback:v=>'$'+v.toFixed(0)}}
      }}
  });
}

const CITY_COORDS={
  'New York':[40.71,-74.01],'London':[51.51,-0.13],'Paris':[48.86,2.35],
  'Hong Kong':[22.32,114.17],'Tokyo':[35.68,139.65],'Seoul':[37.57,126.98],
  'Beijing':[39.90,116.41],'São Paulo':[-23.55,-46.63],'Milan':[45.46,9.19],
  'Los Angeles':[34.05,-118.24],'Houston':[29.76,-95.37],'Austin':[30.27,-97.74],
  'Denver':[39.74,-104.99],'Seattle':[47.61,-122.33],'Chicago':[41.88,-87.63],
  'Phoenix':[33.45,-112.07],'Miami':[25.76,-80.19],'Atlanta':[33.75,-84.39],
  'Boston':[42.36,-71.06],'Toronto':[43.65,-79.38],'Madrid':[40.42,-3.70],
  'Mexico City':[19.43,-99.13]
};

let scene,camera,renderer,globeMesh,gridMesh,atmMesh;
let isDragging=false,prevMouse={x:0,y:0};
let autoRotate=true;
let cityMarkers={};
let globeStats={};

function latLonToVec3(lat,lon,r){
  const phi=(90-lat)*Math.PI/180;
  const theta=(lon+180)*Math.PI/180;
  return new THREE.Vector3(
    -r*Math.sin(phi)*Math.cos(theta),
     r*Math.cos(phi),
     r*Math.sin(phi)*Math.sin(theta)
  );
}

function initGlobe(){
  const wrap=document.getElementById('globe-wrap');
  const W=wrap.clientWidth,H=320;
  scene=new THREE.Scene();
  camera=new THREE.PerspectiveCamera(42,W/H,.1,100);
  camera.position.z=5.5;
  renderer=new THREE.WebGLRenderer({canvas:document.getElementById('globe-canvas'),antialias:true,alpha:true});
  renderer.setSize(W,H);
  renderer.setPixelRatio(window.devicePixelRatio||1);
  scene.add(new THREE.AmbientLight(0x112244,.8));
  const dl=new THREE.DirectionalLight(0x0088ff,1);
  dl.position.set(5,3,5);scene.add(dl);
  const dl2=new THREE.DirectionalLight(0x00ffcc,.3);
  dl2.position.set(-3,-2,-3);scene.add(dl2);
  const geo=new THREE.SphereGeometry(2,64,64);
  const mat=new THREE.MeshPhongMaterial({color:0x061830,emissive:0x030e20,specular:0x0088ff,shininess:40});
  globeMesh=new THREE.Mesh(geo,mat);scene.add(globeMesh);
  const gridMat=new THREE.MeshBasicMaterial({color:0x00e5ff,wireframe:true,transparent:true,opacity:.05});
  gridMesh=new THREE.Mesh(new THREE.SphereGeometry(2.01,36,18),gridMat);
  scene.add(gridMesh);
  const atmGeo=new THREE.SphereGeometry(2.18,64,64);
  const atmMat=new THREE.MeshPhongMaterial({color:0x0066ff,emissive:0x003366,transparent:true,opacity:.12,side:THREE.BackSide});
  atmMesh=new THREE.Mesh(atmGeo,atmMat);scene.add(atmMesh);
  const ringGeo=new THREE.SphereGeometry(2.28,64,64);
  const ringMat=new THREE.MeshBasicMaterial({color:0x0044ff,transparent:true,opacity:.04,side:THREE.BackSide});
  scene.add(new THREE.Mesh(ringGeo,ringMat));
  const cv=document.getElementById('globe-canvas');
  cv.addEventListener('mousedown',e=>{isDragging=true;autoRotate=false;prevMouse={x:e.clientX,y:e.clientY}});
  cv.addEventListener('mousemove',e=>{
    if(isDragging){
      const dx=e.clientX-prevMouse.x,dy=e.clientY-prevMouse.y;
      globeMesh.rotation.y+=dx*.005;globeMesh.rotation.x+=dy*.005;
      gridMesh.rotation.copy(globeMesh.rotation);atmMesh.rotation.copy(globeMesh.rotation);
      prevMouse={x:e.clientX,y:e.clientY};
    }
    handleGlobeHover(e,cv);
  });
  cv.addEventListener('mouseup',()=>isDragging=false);
  cv.addEventListener('mouseleave',()=>{isDragging=false;document.getElementById('globeTip').style.display='none'});
  cv.addEventListener('touchstart',e=>{isDragging=true;autoRotate=false;prevMouse={x:e.touches[0].clientX,y:e.touches[0].clientY}},{passive:true});
  cv.addEventListener('touchmove',e=>{
    if(!isDragging)return;
    const dx=e.touches[0].clientX-prevMouse.x,dy=e.touches[0].clientY-prevMouse.y;
    globeMesh.rotation.y+=dx*.005;globeMesh.rotation.x+=dy*.005;
    gridMesh.rotation.copy(globeMesh.rotation);atmMesh.rotation.copy(globeMesh.rotation);
    prevMouse={x:e.touches[0].clientX,y:e.touches[0].clientY};
  },{passive:true});
  cv.addEventListener('touchend',()=>isDragging=false);
  window.addEventListener('resize',()=>{
    const nw=wrap.clientWidth;
    camera.aspect=nw/H;camera.updateProjectionMatrix();
    renderer.setSize(nw,H);
  });
  animate();
}

let raycaster=null,mouse3d=null;
function handleGlobeHover(e,cv){
  if(!raycaster){raycaster=new THREE.Raycaster();mouse3d=new THREE.Vector2()}
  const rect=cv.getBoundingClientRect();
  mouse3d.x=((e.clientX-rect.left)/rect.width)*2-1;
  mouse3d.y=-((e.clientY-rect.top)/rect.height)*2+1;
  raycaster.setFromCamera(mouse3d,camera);
  const meshes=Object.values(cityMarkers).flatMap(m=>m.meshes||[]);
  const hits=raycaster.intersectObjects(meshes);
  const tip=document.getElementById('globeTip');
  if(hits.length){
    const city=hits[0].object.userData.city;
    const s=globeStats[city]||{};
    const wr=s.wins+s.losses>0?Math.round(s.wins/(s.wins+s.losses)*100):null;
    tip.style.display='block';
    tip.style.left=(e.clientX-cv.getBoundingClientRect().left+12)+'px';
    tip.style.top=(e.clientY-cv.getBoundingClientRect().top-8)+'px';
    tip.innerHTML=`<strong>${city}</strong>
      <span style="color:var(--green)">Win: ${s.wins||0}</span> / <span style="color:var(--red)">Loss: ${s.losses||0}</span><br>
      ${s.open?`<span style="color:var(--amber)">${s.open} abertos</span><br>`:''}
      PnL: <span style="color:${(s.pnl||0)>=0?'var(--green)':'var(--red)'}">${(s.pnl||0)>=0?'+':''}$${Math.abs(s.pnl||0).toFixed(2)}</span>
      ${wr!==null?`<br>Win rate: ${wr}%`:''}`;
  }else{
    tip.style.display='none';
  }
}

let ringPhase=0;
function animate(){
  requestAnimationFrame(animate);
  if(autoRotate){
    globeMesh.rotation.y+=.002;
    gridMesh.rotation.y+=.002;
    atmMesh.rotation.y+=.002;
    Object.values(cityMarkers).forEach(m=>{if(m.pivot)m.pivot.rotation.y+=.002});
  }
  ringPhase+=.05;
  Object.values(cityMarkers).forEach(m=>{
    if(m.ring){
      const sc=1+.15*Math.sin(ringPhase+m.phase);
      m.ring.scale.set(sc,sc,sc);
      m.ring.material.opacity=.3+.2*Math.sin(ringPhase+m.phase);
    }
  });
  renderer.render(scene,camera);
}

function updateGlobe(){
  if(!scene){initGlobe();return}
  const cs=DATA.city_stats;
  globeStats=cs;
  Object.values(cityMarkers).forEach(m=>{if(m.pivot)scene.remove(m.pivot)});
  cityMarkers={};
  Object.entries(CITY_COORDS).forEach(([city,[lat,lon]])=>{
    const stats=cs[city];
    if(!stats)return;
    const total=stats.wins+stats.losses+stats.open;
    if(!total)return;
    const pos=latLonToVec3(lat,lon,2);
    const pnl=stats.pnl||0;
    const hasOpen=stats.open>0;
    const col=pnl>0?0x00ff88:pnl<0?0xff3366:0xffaa00;
    const sz=.04+Math.min(.08,total*.008);
    const pivot=new THREE.Object3D();
    pivot.rotation.copy(globeMesh.rotation);
    scene.add(pivot);
    const mGeo=new THREE.SphereGeometry(sz,12,12);
    const mMat=new THREE.MeshPhongMaterial({color:col,emissive:col,emissiveIntensity:.5});
    const marker=new THREE.Mesh(mGeo,mMat);
    marker.position.copy(pos);
    marker.userData.city=city;
    pivot.add(marker);
    const pts=[pos.clone().multiplyScalar(.98),pos.clone().multiplyScalar(1.04)];
    const lineMat=new THREE.LineBasicMaterial({color:col,transparent:true,opacity:.6});
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),lineMat);
    pivot.add(line);
    let ring=null;
    if(hasOpen){
      const rGeo=new THREE.RingGeometry(sz*1.6,sz*2,20);
      const rMat=new THREE.MeshBasicMaterial({color:0xffaa00,side:THREE.DoubleSide,transparent:true,opacity:.4});
      ring=new THREE.Mesh(rGeo,rMat);
      ring.position.copy(pos);
      ring.lookAt(new THREE.Vector3(0,0,0));
      pivot.add(ring);
    }
    cityMarkers[city]={pivot,meshes:[marker],ring,phase:Math.random()*Math.PI*2};
  });
}

window.addEventListener('load',()=>{if(DATA)updateGlobe();else initGlobe()});
</script>
</body>
</html>"""

# ── HTTP Handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_GET(self):
        if self.path == '/api/stats':
            try:
                data, warning = load_data()
                if data is None:
                    self.send_response(503)
                    self.send_header('Content-Type','application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": warning}).encode())
                    return
                stats = build_stats(data)
                if warning:
                    stats["warning"] = warning
                body = json.dumps(stats, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                err = json.dumps({"error": str(e)}).encode()
                self.send_response(500)
                self.send_header('Content-Type','application/json')
                self.end_headers()
                self.wfile.write(err)

        elif self.path in ('/', '/index.html'):
            body = HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    print(f'Dashboard rodando em http://0.0.0.0:{PORT}')
    try:
        HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\nEncerrado')
