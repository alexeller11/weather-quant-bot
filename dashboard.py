"""
DASHBOARD — WEATHER QUANT BOT
Dashboard profissional com gráficos, mapa-múndi e curva de equity.
CORRIGIDO: f-string SyntaxError na linha 397
"""

import os
import json
import base64
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("PORT", 8765))

# ──────────────────────────────────────────────────────────────
# LOAD DATA — PostgreSQL → GitHub → ERRO
# ──────────────────────────────────────────────────────────────

def load_data():
    """
    Carrega bankroll APENAS de fontes compartilhadas.
    """
    errors = []

    # ── 1. PostgreSQL ──────────────────────────────────────────
    db_url = os.environ.get("DATABASE_URL")
    
    if db_url is None:
        errors.append("DATABASE_URL não configurada")
    elif not db_url.strip():
        errors.append("DATABASE_URL está vazia")
    else:
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM bankroll ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
            conn.close()
            if row:
                print(f"[dashboard] Dados carregados do PostgreSQL")
                return row[0], None
            else:
                errors.append("PostgreSQL conectado mas sem registros")
        except Exception as e:
            errors.append(f"PostgreSQL erro: {str(e)[:100]}")
            print(f"[dashboard] DB erro: {e}")

    # ── 2. GitHub ──────────────────────────────────────────────
    try:
        token  = os.environ.get("GITHUB_TOKEN", "").strip()
        repo   = os.environ.get("GITHUB_REPO", "").strip()
        branch = os.environ.get("GITHUB_BRANCH", "main")
        
        if token and repo:
            import requests
            r = requests.get(
                f"https://api.github.com/repos/{repo}/contents/bankroll.json",
                headers={"Authorization": f"token {token}"},
                params={"ref": branch},
                timeout=10,
            )
            if r.status_code == 200:
                conteudo = base64.b64decode(r.json()["content"]).decode()
                data = json.loads(conteudo)
                print(f"[dashboard] Dados carregados do GitHub")
                return data, "⚠️ Dados do GitHub (PostgreSQL indisponível)"
            else:
                errors.append(f"GitHub HTTP {r.status_code}")
        else:
            if not token:
                errors.append("GITHUB_TOKEN não configurado")
            if not repo:
                errors.append("GITHUB_REPO não configurado")
    except Exception as e:
        errors.append(f"GitHub erro: {str(e)[:100]}")

    error_msg = " | ".join(errors)
    print(f"[dashboard] ERRO: {error_msg}")
    return None, f"ERRO: {error_msg}"


def build_stats(data):
    """Constrói estatísticas para exibição."""
    history  = data.get("history", [])
    balance  = data.get("balance", 0)
    closed   = [t for t in history if t.get("result") in ("WIN","LOSS")]
    open_t   = [t for t in history if t.get("result") == "OPEN"]
    wins     = [t for t in closed if t.get("result") == "WIN"]
    losses   = [t for t in closed if t.get("result") == "LOSS"]
    pnl      = sum(t.get("pnl", 0) for t in closed)
    staked   = sum(t.get("stake", 0) for t in closed)
    exposure = sum(t.get("stake", 0) for t in open_t)
    win_rate = round(len(wins)/len(closed)*100, 1) if closed else 0

    # Por cidade
    city_stats = {}
    for t in history:
        c = t.get("city", "?")
        if c not in city_stats:
            city_stats[c] = {"wins":0,"losses":0,"pnl":0,"stake":0,"open":0}
        if t.get("result") == "WIN":
            city_stats[c]["wins"]  += 1
            city_stats[c]["pnl"]   += t.get("pnl", 0)
        elif t.get("result") == "LOSS":
            city_stats[c]["losses"] += 1
            city_stats[c]["pnl"]    += t.get("pnl", 0)
        elif t.get("result") == "OPEN":
            city_stats[c]["open"] += 1
        city_stats[c]["stake"] += t.get("stake", 0)

    # Curva de equity
    equity_curve = []
    running = float(data.get("start_balance", 50))
    for t in sorted(closed, key=lambda x: x.get("exit_time","") or ""):
        running += t.get("pnl", 0)
        equity_curve.append({
            "date": (t.get("exit_time","") or "")[:10],
            "balance": round(running, 2),
            "city": t.get("city",""),
            "result": t.get("result",""),
        })

    # Edge distribution
    edges = [round(t.get("edge",0)*100, 1) for t in history if t.get("edge")]

    # Calibração
    buckets = {"0-25%":{"total":0,"wins":0},"25-50%":{"total":0,"wins":0},
               "50-75%":{"total":0,"wins":0},"75-100%":{"total":0,"wins":0}}
    for t in closed:
        p = t.get("model_prob", 0)
        if p < 0.25: b = "0-25%"
        elif p < 0.5: b = "25-50%"
        elif p < 0.75: b = "50-75%"
        else: b = "75-100%"
        buckets[b]["total"] += 1
        if t.get("result") == "WIN":
            buckets[b]["wins"] += 1

    return {
        "balance": round(balance, 2),
        "pnl": round(pnl, 2),
        "win_rate": win_rate,
        "total_closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "open_count": len(open_t),
        "exposure": round(exposure, 2),
        "staked": round(staked, 2),
        "city_stats": city_stats,
        "equity_curve": equity_curve,
        "edges": edges,
        "calibration": buckets,
        "open_trades": open_t,
        "closed_trades": list(reversed(closed))[:20],
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


CITY_COORDS = {
    "Seoul": (37.57, 126.98),
    "Tokyo": (35.68, 139.65),
    "Los Angeles": (34.05, -118.24),
    "London": (51.51, -0.13),
    "Paris": (48.86, 2.35),
    "Houston": (29.76, -95.37),
    "Hong Kong": (22.32, 114.17),
    "Milan": (45.46, 9.19),
    "Denver": (39.74, -104.99),
    "Austin": (30.27, -97.74),
    "Seattle": (47.61, -122.33),
    "Beijing": (39.90, 116.41),
    "New York": (40.71, -74.01),
    "Chicago": (41.88, -87.63),
    "Miami": (25.76, -80.19),
    "Toronto": (43.65, -79.38),
    "São Paulo": (-23.55, -46.63),
    "Madrid": (40.42, -3.70),
    "Mexico City": (19.43, -99.13),
    "Phoenix": (33.45, -112.07),
    "Atlanta": (33.75, -84.39),
    "Boston": (42.36, -71.06),
}


def build_error_html(error_msg):
    """Página de erro quando não há dados disponíveis."""
    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="30">
<title>⚡ Weather Quant — Erro</title>
<style>
  body {{ background:#080c10; color:#e6edf3; font-family:'Courier New',monospace;
         display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
  .box {{ background:#0d1117; border:1px solid #ff4466; border-radius:8px; padding:40px;
          max-width:600px; text-align:center; }}
  h1 {{ color:#ff4466; font-size:20px; margin-bottom:16px; }}
  .msg {{ color:#7d8590; font-size:13px; line-height:1.7; margin-bottom:24px; }}
  .code {{ background:#161b22; border-radius:4px; padding:12px; font-size:11px;
           color:#ffaa00; text-align:left; word-break:break-all; }}
  .retry {{ color:#7d8590; font-size:11px; margin-top:20px; }}
</style>
</head>
<body>
<div class="box">
  <h1>⚠️ Sem dados disponíveis</h1>
  <div class="msg">
    O dashboard não conseguiu carregar dados de nenhuma fonte.<br>
    Verifique se o bot está rodando e o PostgreSQL está configurado.
  </div>
  <div class="code">{error_msg}</div>
  <div class="retry">Tentando novamente em 30 segundos...</div>
</div>
</body>
</html>"""


def build_html(stats, warning=None):
    city_stats_json = json.dumps(stats["city_stats"])
    equity_json     = json.dumps(stats["equity_curve"])
    coords_json     = json.dumps(CITY_COORDS)
    edges_json      = json.dumps(stats["edges"])
    cal_json        = json.dumps(stats["calibration"])

    warning_bar = ""
    if warning:
        warning_bar = f"""
        <div style="background:#1a1000;border-bottom:1px solid #ffaa00;
                    padding:8px 32px;font-size:11px;color:#ffaa00;">
          ⚠️ {warning}
        </div>"""

    open_rows = ""
    for t in stats["open_trades"]:
        prob_pct = round(t.get("model_prob",0)*100,1)
        mkt_pct  = round(t.get("market_price",0)*100,1)
        edge_pct = round(t.get("edge",0)*100,1)
        open_rows += f"""
        <tr>
          <td><span class="city-badge">{t.get('city','')}</span></td>
          <td>{t.get('market_date','')}</td>
          <td>${t.get('stake',0):.2f}</td>
          <td class="prob-cell">
            <div class="prob-bar-wrap">
              <div class="prob-bar" style="width:{prob_pct}%"></div>
            </div>
            <span>{prob_pct}%</span>
          </td>
          <td>{mkt_pct}%</td>
          <td class="edge-val">+{edge_pct}%</td>
          <td class="question-cell">{t.get('question','')[:55]}...</td>
        </tr>"""

    closed_rows = ""
    for t in stats["closed_trades"]:
        res   = t.get("result","")
        pnl   = t.get("pnl",0)
        icon  = "✅" if res=="WIN" else "❌"
        cls   = "win-row" if res=="WIN" else "loss-row"
        pnl_cls = "pnl-pos" if pnl >= 0 else "pnl-neg"
        closed_rows += f"""
        <tr class="{cls}">
          <td>{icon}</td>
          <td><span class="city-badge">{t.get('city','')}</span></td>
          <td>{t.get('market_date','')}</td>
          <td>${t.get('stake',0):.2f}</td>
          <td class="{pnl_cls}">${pnl:+.2f}</td>
          <td>{round(t.get('model_prob',0)*100,1)}%</td>
          <td class="question-cell">{t.get('question','')[:55]}...</td>
        </tr>"""

    pnl_color = "#00ff88" if stats["pnl"] >= 0 else "#ff4466"
    pnl_sign  = "+" if stats["pnl"] >= 0 else ""

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>⚡ Weather Quant</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {{
  --bg:       #080c10;
  --bg2:      #0d1117;
  --bg3:      #161b22;
  --border:   #21262d;
  --green:    #00ff88;
  --green2:   #00cc66;
  --red:      #ff4466;
  --amber:    #ffaa00;
  --blue:     #58a6ff;
  --text:     #e6edf3;
  --muted:    #7d8590;
}}
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{ background:var(--bg); color:var(--text); font-family:monospace; font-size:13px; }}
.header {{
  padding:24px 32px 16px;
  border-bottom:1px solid var(--border);
  display:flex; align-items:center; justify-content:space-between;
}}
.header-title {{
  font-size:22px; font-weight:800;
  color:var(--green);
  text-shadow: 0 0 20px rgba(0,255,136,0.3);
}}
.main {{ padding:24px 32px; max-width:1400px; margin:0 auto; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:24px; }}
.kpi {{
  background:var(--bg2); border:1px solid var(--border); border-radius:8px;
  padding:16px; transition:border-color 0.2s;
}}
.kpi:hover {{ border-color:var(--green); }}
.kpi-label {{ font-size:10px; color:var(--muted); text-transform:uppercase; margin-bottom:8px; }}
.kpi-value {{ font-size:26px; font-weight:800; color:var(--green) }}
.kpi-sub {{ font-size:10px; color:var(--muted); margin-top:4px; }}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }}
.card {{
  background:var(--bg2); border:1px solid var(--border); border-radius:8px;
  padding:20px;
}}
.card-title {{
  font-size:12px; font-weight:600;
  text-transform:uppercase; letter-spacing:0.12em;
  color:var(--muted); margin-bottom:16px; display:flex; align-items:center; gap:8px;
}}
.card-title::before {{
  content:''; width:3px; height:14px; background:var(--green); border-radius:2px;
}}
.chart-wrap {{ position:relative; height:250px; }}
.tbl {{ width:100%; border-collapse:collapse; font-size:12px; }}
.tbl th {{
  text-align:left; padding:8px 10px; color:var(--muted);
  font-size:10px; text-transform:uppercase;
  border-bottom:1px solid var(--border);
}}
.tbl td {{ padding:8px 10px; border-bottom:1px solid rgba(33,38,45,0.5); }}
.tbl tr:hover td {{ background:rgba(255,255,255,0.02); }}
.win-row td {{ border-left:3px solid var(--green); }}
.loss-row td {{ border-left:3px solid var(--red); }}
.city-badge {{
  display:inline-block; padding:2px 8px; border-radius:20px;
  background:rgba(88,166,255,0.1); color:var(--blue); font-size:11px;
}}
.prob-cell {{ display:flex; align-items:center; gap:6px; }}
.prob-bar-wrap {{ width:50px; height:4px; background:var(--bg3); border-radius:2px; overflow:hidden; }}
.prob-bar {{ height:100%; background:var(--green); border-radius:2px; }}
.edge-val {{ color:var(--green); font-weight:700; }}
.pnl-pos {{ color:var(--green); font-weight:700; }}
.pnl-neg {{ color:var(--red);   font-weight:700; }}
.question-cell {{ color:var(--muted); font-size:11px; }}
.empty-state {{ color:var(--muted); text-align:center; padding:32px; }}
.tbl-wrap {{ max-height:400px; overflow-y:auto; }}
.tbl-wrap::-webkit-scrollbar {{ width:4px; }}
.tbl-wrap::-webkit-scrollbar-track {{ background:var(--bg3); }}
.tbl-wrap::-webkit-scrollbar-thumb {{ background:var(--border); border-radius:2px; }}
@media(max-width:900px) {{
  .kpi-grid {{ grid-template-columns:repeat(2,1fr); }}
  .grid-2 {{ grid-template-columns:1fr; }}
  .main {{ padding:16px; }}
}}
</style>
</head>
<body>

<div class="header">
  <div class="header-title">⚡ Weather Quant</div>
  <div style="font-size:11px;color:var(--muted);">{stats["updated"]}</div>
</div>

{warning_bar}

<div class="main">

  <div class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">💰 Saldo</div>
      <div class="kpi-value">${stats["balance"]:.2f}</div>
      <div class="kpi-sub">Disponível</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">📈 PnL</div>
      <div class="kpi-value" style="color:{pnl_color}">{pnl_sign}${stats["pnl"]:.2f}</div>
      <div class="kpi-sub">Total</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">🏆 Win Rate</div>
      <div class="kpi-value">{stats["win_rate"]}%</div>
      <div class="kpi-sub">{stats["wins"]}W / {stats["losses"]}L</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">⏳ Abertos</div>
      <div class="kpi-value" style="color:var(--blue)">{stats["open_count"]}</div>
      <div class="kpi-sub">Exposição ${stats["exposure"]:.2f}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">📊 Total</div>
      <div class="kpi-value">{stats["total_closed"]}</div>
      <div class="kpi-sub">Fechados</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">📈 Curva de Equity</div>
      <div class="chart-wrap">
        <canvas id="equityChart"></canvas>
      </div>
    </div>
    <div class="card">
      <div class="card-title">🎯 PnL por Cidade</div>
      <div class="chart-wrap">
        <canvas id="cityChart"></canvas>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">⏳ Posições em Aberto ({stats["open_count"]})</div>
    {('<div class="empty-state">Nenhuma posição aberta.</div>' if not stats["open_trades"] else f'''
    <div class="tbl-wrap">
    <table class="tbl">
      <thead><tr>
        <th>Cidade</th><th>Data</th><th>Stake</th>
        <th>Prob</th><th>Mkt</th><th>Edge</th><th>Pergunta</th>
      </tr></thead>
      <tbody>{open_rows}</tbody>
    </table>
    </div>''')}
  </div>

  <div class="card">
    <div class="card-title">📋 Últimos Trades</div>
    {('<div class="empty-state">Nenhum trade fechado ainda.</div>' if not stats["closed_trades"] else f'''
    <div class="tbl-wrap">
    <table class="tbl">
      <thead><tr>
        <th></th><th>Cidade</th><th>Data</th><th>Stake</th>
        <th>PnL</th><th>Prob</th><th>Pergunta</th>
      </tr></thead>
      <tbody>{closed_rows}</tbody>
    </table>
    </div>''')}
  </div>

</div>

<script>
const CITY_STATS  = {city_stats_json};
const EQUITY      = {equity_json};

const eqCtx = document.getElementById('equityChart').getContext('2d');
if (EQUITY.length > 0) {{
  new Chart(eqCtx, {{
    type: 'line',
    data: {{
      labels: EQUITY.map(p => p.date),
      datasets: [{{ data: EQUITY.map(p => p.balance),
        borderColor: '#00ff88', backgroundColor: 'rgba(0,255,136,0.08)',
        fill: true, tension: 0.4, pointRadius: 4,
        pointBackgroundColor: EQUITY.map(p => p.result==='WIN'?'#00ff88':'#ff4466'),
        pointBorderColor: '#080c10', pointBorderWidth: 2 }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}} }},
      scales:{{
        x:{{ grid:{{color:'#21262d'}}, ticks:{{color:'#7d8590',font:{{size:10}}}} }},
        y:{{ grid:{{color:'#21262d'}}, ticks:{{color:'#7d8590',font:{{size:10}}, callback: v => '$'+v.toFixed(0) }} }}
      }}
    }}
  }});
}} else {{ eqCtx.canvas.parentElement.innerHTML = '<div class="empty-state">Sem trades fechados</div>'; }}

const cities  = Object.keys(CITY_STATS).filter(c => CITY_STATS[c].wins + CITY_STATS[c].losses > 0);
const cityCtx = document.getElementById('cityChart').getContext('2d');
if (cities.length > 0) {{
  new Chart(cityCtx, {{
    type: 'bar',
    data: {{
      labels: cities,
      datasets: [{{ data: cities.map(c => CITY_STATS[c].pnl),
        backgroundColor: cities.map(c => CITY_STATS[c].pnl >= 0 ? 'rgba(0,255,136,0.7)' : 'rgba(255,68,102,0.7)'),
        borderColor:     cities.map(c => CITY_STATS[c].pnl >= 0 ? '#00ff88' : '#ff4466'),
        borderWidth: 1, borderRadius: 4 }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}} }},
      scales:{{
        x:{{ grid:{{display:false}}, ticks:{{color:'#7d8590',font:{{size:9}}}} }},
        y:{{ grid:{{color:'#21262d'}}, ticks:{{color:'#7d8590',font:{{size:10}}, callback: v => '$'+v.toFixed(2) }} }}
      }}
    }}
  }});
}} else {{ cityCtx.canvas.parentElement.innerHTML = '<div class="empty-state">Aguardando trades</div>'; }}

setTimeout(() => location.reload(), 15000);
</script>

</body>
</html>"""

    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        
        try:
            data, warning = load_data()

            if data is None:
                html = build_error_html(warning or "Fonte de dados indisponível").encode("utf-8")
                self.send_response(503)
            else:
                stats = build_stats(data)
                html  = build_html(stats, warning=warning)
                self.send_response(200)

            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(html))
            self.end_headers()
            self.wfile.write(html)
        except Exception as e:
            err = f"<h1>Erro</h1><pre>{str(e)[:500]}</pre>".encode()
            self.send_response(500)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length", len(err))
            self.end_headers()
            self.wfile.write(err)


if __name__ == "__main__":
    print(f"Dashboard rodando em http://0.0.0.0:{PORT}")
    print(f"Fonte: PostgreSQL (DATABASE_URL)")
    try:
        HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard parado")
