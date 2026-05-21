"""
DASHBOARD — WEATHER QUANT BOT
Dashboard profissional com gráficos, mapa-múndi e curva de equity.
"""

import os
import json
import base64
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

BANKROLL_FILE = "bankroll.json"
PORT = int(os.environ.get("PORT", 8765))

# ──────────────────────────────────────────────────────────────
# LOAD DATA — PostgreSQL → local → GitHub
# ──────────────────────────────────────────────────────────────

def load_data():
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM bankroll ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
            conn.close()
            if row:
                return row[0]
        except Exception as e:
            print(f"[dashboard] DB erro: {e}")

    if os.path.exists(BANKROLL_FILE):
        try:
            with open(BANKROLL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    try:
        token  = os.environ.get("GITHUB_TOKEN", "")
        repo   = os.environ.get("GITHUB_REPO", "")
        branch = os.environ.get("GITHUB_BRANCH", "main")
        if token and repo:
            import requests as req
            r = req.get(
                f"https://api.github.com/repos/{repo}/contents/bankroll.json",
                headers={"Authorization": f"token {token}"},
                params={"ref": branch},
                timeout=10,
            )
            if r.status_code == 200:
                conteudo = base64.b64decode(r.json()["content"]).decode()
                return json.loads(conteudo)
    except Exception:
        pass

    return {"balance": 0, "history": []}


def build_stats(data):
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
            city_stats[c] = {"wins":0,"losses":0,"pnl":0,"stake":0,"open":0,
                              "lat":0,"lon":0}
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
    running = data.get("start_balance", 50)
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

    # Model prob vs win rate (calibração)
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


# ──────────────────────────────────────────────────────────────
# COORDENADAS PARA O MAPA
# ──────────────────────────────────────────────────────────────

CITY_COORDS = {
    "Seoul":        (37.57, 126.98),
    "Tokyo":        (35.68, 139.65),
    "Los Angeles":  (34.05, -118.24),
    "London":       (51.51, -0.13),
    "Paris":        (48.86, 2.35),
    "Houston":      (29.76, -95.37),
    "Hong Kong":    (22.32, 114.17),
    "Milan":        (45.46, 9.19),
    "Denver":       (39.74, -104.99),
    "Austin":       (30.27, -97.74),
    "Seattle":      (47.61, -122.33),
    "Beijing":      (39.90, 116.41),
    "Wellington":   (-41.29, 174.78),
    "New York":     (40.71, -74.01),
    "Chicago":      (41.88, -87.63),
    "Miami":        (25.76, -80.19),
    "San Francisco":(37.77, -122.42),
    "Toronto":      (43.65, -79.38),
    "Sydney":       (-33.87, 151.21),
    "Singapore":    (1.35, 103.82),
    "Dubai":        (25.20, 55.27),
    "Amsterdam":    (52.37, 4.90),
    "Berlin":       (52.52, 13.41),
    "Madrid":       (40.42, -3.70),
    "Bangkok":      (13.76, 100.50),
    "Mumbai":       (19.08, 72.88),
    "Johannesburg": (-26.20, 28.05),
    "Mexico City":  (19.43, -99.13),
    "Buenos Aires": (-34.60, -58.38),
    "São Paulo":    (-23.55, -46.63),
    "Lagos":        (6.52, 3.38),
    "Cairo":        (30.04, 31.24),
}


def build_html(stats):
    city_stats_json = json.dumps(stats["city_stats"])
    equity_json     = json.dumps(stats["equity_curve"])
    coords_json     = json.dumps(CITY_COORDS)
    edges_json      = json.dumps(stats["edges"])
    cal_json        = json.dumps(stats["calibration"])

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
        closed_rows += f"""
        <tr class="{cls}">
          <td>{icon}</td>
          <td><span class="city-badge">{t.get('city','')}</span></td>
          <td>{t.get('market_date','')}</td>
          <td>${t.get('stake',0):.2f}</td>
          <td class="{'pnl-pos' if pnl>=0 else 'pnl-neg'}">${pnl:+.2f}</td>
          <td>{round(t.get('model_prob',0)*100,1)}%</td>
          <td class="question-cell">{t.get('question','')[:55]}...</td>
        </tr>"""

    pnl_color = "#00ff88" if stats["pnl"] >= 0 else "#ff4466"
    pnl_sign  = "+" if stats["pnl"] >= 0 else ""

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>⚡ Weather Quant</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap" rel="stylesheet">
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
  --font-h:   'Syne', sans-serif;
  --font-m:   'Space Mono', monospace;
}}
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{ background:var(--bg); color:var(--text); font-family:var(--font-m); font-size:13px; }}

/* SCANLINES */
body::before {{
  content:''; position:fixed; inset:0; pointer-events:none; z-index:999;
  background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,255,136,0.015) 2px, rgba(0,255,136,0.015) 4px);
}}

.header {{
  padding:24px 32px 16px;
  border-bottom:1px solid var(--border);
  display:flex; align-items:center; justify-content:space-between;
  background: linear-gradient(180deg, rgba(0,255,136,0.04) 0%, transparent 100%);
}}
.header-title {{
  font-family:var(--font-h); font-size:22px; font-weight:800;
  letter-spacing:0.1em; text-transform:uppercase;
  color:var(--green);
  text-shadow: 0 0 20px rgba(0,255,136,0.5);
}}
.header-sub {{ font-size:11px; color:var(--muted); margin-top:2px; }}
.live-dot {{
  width:8px; height:8px; border-radius:50%; background:var(--green);
  animation: pulse 2s infinite; display:inline-block; margin-right:6px;
}}
@keyframes pulse {{ 0%,100%{{box-shadow:0 0 0 0 rgba(0,255,136,0.4)}} 50%{{box-shadow:0 0 0 6px rgba(0,255,136,0)}} }}

.main {{ padding:24px 32px; max-width:1400px; margin:0 auto; }}

/* KPI CARDS */
.kpi-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:24px; }}
.kpi {{
  background:var(--bg2); border:1px solid var(--border); border-radius:8px;
  padding:16px; position:relative; overflow:hidden;
  transition: border-color 0.2s;
}}
.kpi:hover {{ border-color:var(--green); }}
.kpi::before {{
  content:''; position:absolute; top:0; left:0; right:0; height:2px;
  background:linear-gradient(90deg, var(--green), transparent);
}}
.kpi-label {{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:8px; }}
.kpi-value {{ font-family:var(--font-h); font-size:26px; font-weight:800; }}
.kpi-sub {{ font-size:10px; color:var(--muted); margin-top:4px; }}
.green {{ color:var(--green) }}
.red   {{ color:var(--red)   }}
.amber {{ color:var(--amber) }}
.blue  {{ color:var(--blue)  }}

/* GRID DE SEÇÕES */
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }}
.grid-3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; margin-bottom:16px; }}
.grid-full {{ margin-bottom:16px; }}

.card {{
  background:var(--bg2); border:1px solid var(--border); border-radius:8px;
  padding:20px;
}}
.card-title {{
  font-family:var(--font-h); font-size:12px; font-weight:600;
  text-transform:uppercase; letter-spacing:0.12em;
  color:var(--muted); margin-bottom:16px;
  display:flex; align-items:center; gap:8px;
}}
.card-title::before {{
  content:''; width:3px; height:14px; background:var(--green); border-radius:2px;
}}

/* MAPA */
#world-map {{
  width:100%; height:340px; position:relative;
  background:var(--bg3); border-radius:6px; overflow:hidden;
}}
#map-svg {{ width:100%; height:100%; }}
.map-dot {{
  cursor:pointer; transition:r 0.2s;
}}
.map-dot:hover {{ r:8; }}
.map-tooltip {{
  position:absolute; background:#1a2030; border:1px solid var(--green);
  border-radius:6px; padding:8px 12px; font-size:11px; pointer-events:none;
  display:none; z-index:10; white-space:nowrap;
}}

/* CHARTS */
.chart-wrap {{ position:relative; height:200px; }}
.chart-wrap-tall {{ position:relative; height:260px; }}

/* TABELAS */
.tbl {{ width:100%; border-collapse:collapse; font-size:12px; }}
.tbl th {{
  text-align:left; padding:8px 10px; color:var(--muted);
  font-size:10px; text-transform:uppercase; letter-spacing:0.08em;
  border-bottom:1px solid var(--border);
}}
.tbl td {{ padding:8px 10px; border-bottom:1px solid rgba(33,38,45,0.5); }}
.tbl tr:last-child td {{ border-bottom:none; }}
.tbl tr:hover td {{ background:rgba(255,255,255,0.02); }}
.win-row td {{ border-left:2px solid var(--green); }}
.loss-row td {{ border-left:2px solid var(--red); }}
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

.empty-state {{ color:var(--muted); text-align:center; padding:32px; font-size:12px; }}

/* SCROLLABLE TABLE */
.tbl-wrap {{ max-height:320px; overflow-y:auto; }}
.tbl-wrap::-webkit-scrollbar {{ width:4px; }}
.tbl-wrap::-webkit-scrollbar-track {{ background:var(--bg3); }}
.tbl-wrap::-webkit-scrollbar-thumb {{ background:var(--border); border-radius:2px; }}

.updated-bar {{
  text-align:center; padding:12px; font-size:10px; color:var(--muted);
  border-top:1px solid var(--border); margin-top:8px;
}}

@media(max-width:900px) {{
  .kpi-grid {{ grid-template-columns:repeat(2,1fr); }}
  .grid-2, .grid-3 {{ grid-template-columns:1fr; }}
  .main {{ padding:16px; }}
}}
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="header-title">⚡ Weather Quant Bot</div>
    <div class="header-sub"><span class="live-dot"></span>Live · Atualiza a cada 15s</div>
  </div>
  <div style="text-align:right;font-size:11px;color:var(--muted)">
    {stats["updated"]}
  </div>
</div>

<div class="main">

  <!-- KPI CARDS -->
  <div class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">💰 Saldo</div>
      <div class="kpi-value green">${stats["balance"]:.2f}</div>
      <div class="kpi-sub">Disponível</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">📈 PnL Total</div>
      <div class="kpi-value" style="color:{pnl_color}">{pnl_sign}${stats["pnl"]:.2f}</div>
      <div class="kpi-sub">Trades fechados</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">🏆 Win Rate</div>
      <div class="kpi-value {'green' if stats['win_rate']>=55 else 'amber'}">{stats["win_rate"]}%</div>
      <div class="kpi-sub">{stats["wins"]}W / {stats["losses"]}L</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">⏳ Em Aberto</div>
      <div class="kpi-value blue">{stats["open_count"]}</div>
      <div class="kpi-sub">Exposição ${stats["exposure"]:.2f}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">📊 Total Trades</div>
      <div class="kpi-value">{stats["total_closed"]}</div>
      <div class="kpi-sub">Fechados</div>
    </div>
  </div>

  <!-- MAPA + EQUITY CURVE -->
  <div class="grid-2">
    <div class="card">
      <div class="card-title">🌍 Mapa de Posições</div>
      <div id="world-map">
        <svg id="map-svg" viewBox="0 0 1000 500" preserveAspectRatio="xMidYMid meet">
          <!-- Simplified world map paths -->
          <rect width="1000" height="500" fill="#0d1117"/>
          <!-- Grid lines -->
          <line x1="0" y1="250" x2="1000" y2="250" stroke="#21262d" stroke-width="0.5"/>
          <line x1="500" y1="0" x2="500" y2="500" stroke="#21262d" stroke-width="0.5"/>
          <!-- Continents simplified -->
          <!-- North America -->
          <path d="M80,80 L200,70 L230,120 L220,200 L180,220 L150,280 L100,290 L80,240 L60,180 Z" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
          <!-- South America -->
          <path d="M160,290 L220,280 L240,320 L230,400 L190,440 L160,420 L140,370 L150,320 Z" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
          <!-- Europe -->
          <path d="M440,60 L520,55 L530,90 L510,120 L470,130 L440,110 Z" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
          <!-- Africa -->
          <path d="M450,130 L520,120 L550,160 L540,260 L500,310 L460,290 L440,230 L440,160 Z" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
          <!-- Asia -->
          <path d="M530,55 L780,60 L800,100 L780,160 L720,180 L680,150 L620,160 L580,140 L540,120 L530,90 Z" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
          <!-- Southeast Asia -->
          <path d="M700,180 L760,170 L770,210 L740,240 L700,230 L690,200 Z" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
          <!-- Australia -->
          <path d="M730,290 L820,280 L840,340 L800,380 L740,370 L710,330 Z" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
          <!-- Middle East -->
          <path d="M540,130 L610,120 L620,160 L590,180 L550,170 Z" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        </svg>
        <div class="map-tooltip" id="map-tooltip"></div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">📈 Curva de Equity</div>
      <div class="chart-wrap-tall">
        <canvas id="equityChart"></canvas>
      </div>
    </div>
  </div>

  <!-- CHARTS ROW -->
  <div class="grid-3">
    <div class="card">
      <div class="card-title">🏙️ PnL por Cidade</div>
      <div class="chart-wrap">
        <canvas id="cityChart"></canvas>
      </div>
    </div>
    <div class="card">
      <div class="card-title">🎯 Distribuição de Edge</div>
      <div class="chart-wrap">
        <canvas id="edgeChart"></canvas>
      </div>
    </div>
    <div class="card">
      <div class="card-title">🔬 Calibração do Modelo</div>
      <div class="chart-wrap">
        <canvas id="calChart"></canvas>
      </div>
    </div>
  </div>

  <!-- OPEN TRADES TABLE -->
  <div class="card grid-full">
    <div class="card-title">⏳ Posições em Aberto ({stats["open_count"]})</div>
    {'<div class="empty-state">Nenhuma posição aberta. Bot aguardando oportunidades.</div>' if not stats["open_trades"] else f'''
    <div class="tbl-wrap">
    <table class="tbl">
      <thead><tr>
        <th>Cidade</th><th>Data</th><th>Aposta</th>
        <th>Prob Modelo</th><th>Mercado</th><th>Edge</th><th>Pergunta</th>
      </tr></thead>
      <tbody>{open_rows}</tbody>
    </table>
    </div>'''}
  </div>

  <!-- CLOSED TRADES -->
  <div class="card grid-full">
    <div class="card-title">📋 Trades Recentes</div>
    {'<div class="empty-state">Nenhum trade fechado ainda.</div>' if not stats["closed_trades"] else f'''
    <div class="tbl-wrap">
    <table class="tbl">
      <thead><tr>
        <th></th><th>Cidade</th><th>Data</th><th>Aposta</th>
        <th>PnL</th><th>Prob</th><th>Pergunta</th>
      </tr></thead>
      <tbody>{closed_rows}</tbody>
    </table>
    </div>'''}
  </div>

</div>

<div class="updated-bar">
  ⚡ Weather Quant Bot · Atualiza automaticamente a cada 15 segundos
</div>

<script>
const CITY_STATS  = {city_stats_json};
const EQUITY      = {equity_json};
const COORDS      = {coords_json};
const EDGES       = {edges_json};
const CALIBRATION = {cal_json};

// ── MAPA ─────────────────────────────────────────────────────
function latLonToXY(lat, lon) {{
  const x = (lon + 180) / 360 * 1000;
  const y = (90 - lat) / 180 * 500;
  return [x, y];
}}

const svg       = document.getElementById('map-svg');
const tooltip   = document.getElementById('map-tooltip');
const mapEl     = document.getElementById('world-map');

Object.entries(CITY_STATS).forEach(([city, stats]) => {{
  const coord = COORDS[city];
  if (!coord) return;
  const [x, y] = latLonToXY(coord[0], coord[1]);
  const total = stats.wins + stats.losses;
  const wr    = total > 0 ? stats.wins / total : 0;
  const color = stats.open > 0 && total === 0 ? '#58a6ff'
              : wr >= 0.6 ? '#00ff88'
              : wr >= 0.4 ? '#ffaa00' : '#ff4466';
  const r = Math.max(5, Math.min(12, 4 + stats.wins + stats.losses + stats.open));

  // Glow circle
  const glow = document.createElementNS('http://www.w3.org/2000/svg','circle');
  glow.setAttribute('cx', x); glow.setAttribute('cy', y);
  glow.setAttribute('r', r + 4);
  glow.setAttribute('fill', color); glow.setAttribute('opacity','0.15');
  svg.appendChild(glow);

  // Main dot
  const circle = document.createElementNS('http://www.w3.org/2000/svg','circle');
  circle.setAttribute('cx', x); circle.setAttribute('cy', y);
  circle.setAttribute('r', r);
  circle.setAttribute('fill', color);
  circle.setAttribute('stroke', '#080c10');
  circle.setAttribute('stroke-width', '1.5');
  circle.classList.add('map-dot');
  circle.addEventListener('mouseenter', (e) => {{
    const pnl  = stats.pnl >= 0 ? '+$' + stats.pnl.toFixed(2) : '-$' + Math.abs(stats.pnl).toFixed(2);
    const wrPct = total > 0 ? (wr*100).toFixed(0) + '%' : '—';
    tooltip.innerHTML = `<b>${{city}}</b><br>W/L: ${{stats.wins}}/${{stats.losses}} · WR: ${{wrPct}}<br>PnL: ${{pnl}} · Abertos: ${{stats.open}}`;
    tooltip.style.display = 'block';
  }});
  circle.addEventListener('mousemove', (e) => {{
    const rect = mapEl.getBoundingClientRect();
    tooltip.style.left = (e.clientX - rect.left + 12) + 'px';
    tooltip.style.top  = (e.clientY - rect.top  - 10) + 'px';
  }});
  circle.addEventListener('mouseleave', () => {{ tooltip.style.display = 'none'; }});
  svg.appendChild(circle);
}});

// ── EQUITY CURVE ─────────────────────────────────────────────
const eqCtx = document.getElementById('equityChart').getContext('2d');
if (EQUITY.length > 0) {{
  new Chart(eqCtx, {{
    type: 'line',
    data: {{
      labels: EQUITY.map(p => p.date),
      datasets: [{{
        data: EQUITY.map(p => p.balance),
        borderColor: '#00ff88',
        backgroundColor: 'rgba(0,255,136,0.08)',
        fill: true,
        tension: 0.4,
        pointRadius: 4,
        pointBackgroundColor: EQUITY.map(p => p.result==='WIN'?'#00ff88':'#ff4466'),
        pointBorderColor: '#080c10',
        pointBorderWidth: 2,
      }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}}, tooltip:{{
        callbacks:{{ label: ctx => ' $' + ctx.parsed.y.toFixed(2) }}
      }}}},
      scales:{{
        x:{{ grid:{{color:'#21262d'}}, ticks:{{color:'#7d8590',font:{{size:10}}}} }},
        y:{{ grid:{{color:'#21262d'}}, ticks:{{color:'#7d8590',font:{{size:10}},
          callback: v => '$'+v.toFixed(0) }} }}
      }}
    }}
  }});
}} else {{
  eqCtx.canvas.parentElement.innerHTML = '<div class="empty-state">Nenhum trade fechado ainda</div>';
}}

// ── PNL POR CIDADE ────────────────────────────────────────────
const cities = Object.keys(CITY_STATS).filter(c => CITY_STATS[c].wins + CITY_STATS[c].losses > 0);
const cityCtx = document.getElementById('cityChart').getContext('2d');
if (cities.length > 0) {{
  new Chart(cityCtx, {{
    type: 'bar',
    data: {{
      labels: cities,
      datasets: [{{
        data: cities.map(c => CITY_STATS[c].pnl),
        backgroundColor: cities.map(c => CITY_STATS[c].pnl >= 0 ? 'rgba(0,255,136,0.7)' : 'rgba(255,68,102,0.7)'),
        borderColor:     cities.map(c => CITY_STATS[c].pnl >= 0 ? '#00ff88' : '#ff4466'),
        borderWidth: 1, borderRadius: 4,
      }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}} }},
      scales:{{
        x:{{ grid:{{display:false}}, ticks:{{color:'#7d8590',font:{{size:10}}}} }},
        y:{{ grid:{{color:'#21262d'}}, ticks:{{color:'#7d8590',font:{{size:10}},
          callback: v => '$'+v.toFixed(2) }} }}
      }}
    }}
  }});
}} else {{
  cityCtx.canvas.parentElement.innerHTML = '<div class="empty-state">Aguardando trades fechados</div>';
}}

// ── EDGE DISTRIBUTION ─────────────────────────────────────────
const edgeCtx = document.getElementById('edgeChart').getContext('2d');
if (EDGES.length > 0) {{
  const bins = {{}};
  EDGES.forEach(e => {{
    const b = Math.floor(e / 5) * 5;
    bins[b] = (bins[b] || 0) + 1;
  }});
  const bLabels = Object.keys(bins).sort((a,b)=>+a-+b).map(b => b+'%');
  const bVals   = Object.keys(bins).sort((a,b)=>+a-+b).map(b => bins[b]);
  new Chart(edgeCtx, {{
    type: 'bar',
    data: {{
      labels: bLabels,
      datasets: [{{ data: bVals,
        backgroundColor:'rgba(88,166,255,0.6)', borderColor:'#58a6ff',
        borderWidth:1, borderRadius:4 }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}} }},
      scales:{{
        x:{{ grid:{{display:false}}, ticks:{{color:'#7d8590',font:{{size:10}}}} }},
        y:{{ grid:{{color:'#21262d'}}, ticks:{{color:'#7d8590',font:{{size:10}}}} }}
      }}
    }}
  }});
}} else {{
  edgeCtx.canvas.parentElement.innerHTML = '<div class="empty-state">Aguardando dados</div>';
}}

// ── CALIBRAÇÃO ───────────────────────────────────────────────
const calCtx = document.getElementById('calChart').getContext('2d');
const calLabels = Object.keys(CALIBRATION);
const calPred   = [12.5, 37.5, 62.5, 87.5];
const calReal   = calLabels.map(k => {{
  const b = CALIBRATION[k];
  return b.total > 0 ? b.wins/b.total*100 : null;
}});
new Chart(calCtx, {{
  type: 'bar',
  data: {{
    labels: calLabels,
    datasets: [
      {{ label:'Previsto', data:calPred, backgroundColor:'rgba(255,170,0,0.3)',
         borderColor:'#ffaa00', borderWidth:1, borderRadius:4 }},
      {{ label:'Real', data:calReal, backgroundColor:'rgba(0,255,136,0.6)',
         borderColor:'#00ff88', borderWidth:1, borderRadius:4 }}
    ]
  }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    plugins:{{ legend:{{labels:{{color:'#7d8590',font:{{size:10}}}}}} }},
    scales:{{
      x:{{ grid:{{display:false}}, ticks:{{color:'#7d8590',font:{{size:10}}}} }},
      y:{{ grid:{{color:'#21262d'}}, ticks:{{color:'#7d8590',font:{{size:10}},
        callback: v => v+'%' }}, max:100 }}
    }}
  }}
}});

// ── AUTO REFRESH ─────────────────────────────────────────────
setTimeout(() => location.reload(), 15000);
</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────
# HTTP SERVER
# ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silencia logs de request

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404); self.end_headers(); return
        try:
            data  = load_data()
            stats = build_stats(data)
            html  = build_html(stats).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(html))
            self.end_headers()
            self.wfile.write(html)
        except Exception as e:
            err = f"<h1>Erro</h1><pre>{e}</pre>".encode()
            self.send_response(500)
            self.send_header("Content-Type","text/html")
            self.end_headers()
            self.wfile.write(err)


if __name__ == "__main__":
    print(f"Dashboard rodando em http://0.0.0.0:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
