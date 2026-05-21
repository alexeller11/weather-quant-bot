"""
DASHBOARD WEATHER QUANT BOT — Português + Claro
USO: python dashboard.py
Abre http://localhost:8765 | Atualiza a cada 10s
"""

import json, os, http.server, socketserver, threading
from datetime import datetime, timezone

BANKROLL_FILE = "bankroll.json"
PORT = int(os.environ.get("PORT", 8765))  # Railway injeta PORT automaticamente

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def load_data():
    # 1. Tenta PostgreSQL primeiro (fonte mais atualizada)
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

    # 2. Tenta arquivo local
    if os.path.exists(BANKROLL_FILE):
        try:
            with open(BANKROLL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass

    # 3. Fallback: GitHub
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
                import base64
                conteudo = base64.b64decode(r.json()["content"]).decode()
                return json.loads(conteudo)
    except:
        pass
    return {"balance": 0, "history": []}

def calcular_stats(bankroll):
    history = bankroll.get("history", [])
    balance = bankroll.get("balance", 0)
    
    # Separar trades
    fechados = [t for t in history if t.get("result") in ("WIN", "LOSS")]
    abertos = [t for t in history if t.get("result") == "OPEN"]
    ganhos = [t for t in fechados if t.get("result") == "WIN"]
    perdidos = [t for t in fechados if t.get("result") == "LOSS"]
    
    # Cálculos
    pnl_total = sum(t.get("pnl", 0) for t in fechados)
    exposicao = sum(t.get("stake", 0) for t in abertos)
    taxa_vitoria = (len(ganhos) / len(fechados) * 100) if fechados else 0
    
    # Curva de lucro
    curva = []
    acumulado = 0
    for t in fechados:
        acumulado += t.get("pnl", 0)
        curva.append(int(acumulado))
    
    # Por cidade
    por_cidade = {}
    for t in fechados:
        cidade = t.get("city", "?")
        if cidade not in por_cidade:
            por_cidade[cidade] = {"ganhos": 0, "perdas": 0, "pnl": 0}
        if t.get("result") == "WIN":
            por_cidade[cidade]["ganhos"] += 1
        else:
            por_cidade[cidade]["perdas"] += 1
        por_cidade[cidade]["pnl"] = round(por_cidade[cidade]["pnl"] + t.get("pnl", 0), 2)
    
    # Trades recentes (últimos 10)
    recentes = []
    for t in reversed(fechados[-10:]):
        recentes.append({
            "cidade": t.get("city", "?"),
            "resultado": "✅ WIN" if t.get("result") == "WIN" else "❌ LOSS",
            "pnl": t.get("pnl", 0),
            "stake": t.get("stake", 0),
            "data": t.get("market_date", "?"),
            "pergunta": t.get("question", "")[:60]
        })
    
    # Trades em aberto
    em_aberto = []
    for t in abertos:
        em_aberto.append({
            "cidade": t.get("city", "?"),
            "stake": t.get("stake", 0),
            "probabilidade": t.get("model_prob", 0),
            "preco_mercado": t.get("market_price", 0),
            "data": t.get("market_date", "?"),
            "pergunta": t.get("question", "")[:60]
        })
    
    return {
        "saldo": round(balance, 2),
        "pnl_total": round(pnl_total, 2),
        "exposicao_aberta": round(exposicao, 2),
        "taxa_vitoria": round(taxa_vitoria, 1),
        "total_fechados": len(fechados),
        "ganhos": len(ganhos),
        "perdidos": len(perdidos),
        "abertos": len(abertos),
        "curva": curva,
        "por_cidade": por_cidade,
        "recentes": recentes,
        "em_aberto": em_aberto,
        "atualizado": utcnow().isoformat(),
    }

HTML = r"""<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>⚡ WEATHER QUANT BOT</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: #0a0e0e;
            color: #e0e0e0;
            padding: 20px;
            line-height: 1.6;
        }
        
        .container { max-width: 1400px; margin: 0 auto; }
        
        h1 {
            text-align: center;
            color: #00ff88;
            font-size: 28px;
            margin-bottom: 30px;
            text-shadow: 0 0 10px #00ff88;
        }
        
        .header {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .card {
            background: linear-gradient(135deg, #1a2020 0%, #0d1515 100%);
            border: 2px solid #00ff88;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 0 20px rgba(0, 255, 136, 0.2);
        }
        
        .card.danger { border-color: #ff4444; }
        .card.warning { border-color: #ffaa00; }
        
        .label {
            color: #00ccaa;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }
        
        .valor {
            font-size: 24px;
            font-weight: bold;
            color: #00ff88;
        }
        
        .valor.negativo { color: #ff4444; }
        .valor.positivo { color: #00ff88; }
        
        .subsection {
            margin-bottom: 10px;
            font-size: 12px;
            color: #888;
        }
        
        .section {
            margin-top: 40px;
        }
        
        .section-title {
            font-size: 18px;
            color: #00ffaa;
            border-bottom: 2px solid #00ff88;
            padding-bottom: 10px;
            margin-bottom: 20px;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }
        
        .stat-item {
            background: #0d1515;
            border: 1px solid #00aa66;
            padding: 15px;
            border-radius: 6px;
        }
        
        .stat-label {
            color: #00aa66;
            font-size: 11px;
            text-transform: uppercase;
        }
        
        .stat-value {
            font-size: 20px;
            color: #00ff88;
            margin-top: 5px;
            font-weight: bold;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        
        th {
            background: #1a2020;
            color: #00ffaa;
            padding: 12px;
            text-align: left;
            border-bottom: 2px solid #00ff88;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #0d1515;
            font-size: 12px;
        }
        
        tr:hover { background: #1a2525; }
        
        .win { color: #00ff88; }
        .loss { color: #ff4444; }
        
        .chart {
            background: #0d1515;
            padding: 20px;
            border: 1px solid #00aa66;
            border-radius: 6px;
            margin-top: 15px;
            height: 200px;
            position: relative;
        }
        
        .timestamp {
            text-align: center;
            color: #666;
            font-size: 11px;
            margin-top: 20px;
        }
        
        .info-box {
            background: #1a3030;
            border-left: 4px solid #00ff88;
            padding: 15px;
            margin: 15px 0;
            border-radius: 4px;
        }
        
        .row {
            display: flex;
            gap: 20px;
            margin-top: 20px;
            flex-wrap: wrap;
        }
        
        .col { flex: 1; min-width: 300px; }
        
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            margin: 5px 0;
        }
        
        .badge-win { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
        .badge-loss { background: #ff444422; color: #ff4444; border: 1px solid #ff4444; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ WEATHER QUANT BOT</h1>
        
        <!-- CARDS PRINCIPAIS -->
        <div class="header" id="cards">
            <div class="card">
                <div class="label">💰 Saldo</div>
                <div class="valor" id="saldo">$0.00</div>
            </div>
            <div class="card">
                <div class="label">📈 Lucro Total</div>
                <div class="valor positivo" id="pnl">$0.00</div>
            </div>
            <div class="card">
                <div class="label">📊 Taxa de Vitória</div>
                <div class="valor" id="taxa">0%</div>
            </div>
            <div class="card">
                <div class="label">⏳ Posições em Aberto</div>
                <div class="valor" id="abertos">0</div>
                <div class="subsection" id="exposicao">Exposição: $0</div>
            </div>
        </div>
        
        <!-- SEÇÃO: ESTATÍSTICAS -->
        <div class="section">
            <div class="section-title">📋 Estatísticas Gerais</div>
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-label">Total de Trades Fechados</div>
                    <div class="stat-value" id="total_fechados">0</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Vitórias ✅</div>
                    <div class="stat-value win" id="ganhos">0</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Derrotas ❌</div>
                    <div class="stat-value loss" id="perdidos">0</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Posições Abertas ⏳</div>
                    <div class="stat-value" id="abertos2">0</div>
                </div>
            </div>
        </div>
        
        <!-- SEÇÃO: POR CIDADE -->
        <div class="section">
            <div class="section-title">🌍 Desempenho Por Cidade</div>
            <table id="cidades-table">
                <thead>
                    <tr>
                        <th>Cidade</th>
                        <th>Vitórias</th>
                        <th>Derrotas</th>
                        <th>Lucro/Prejuízo</th>
                    </tr>
                </thead>
                <tbody id="cidades-body"></tbody>
            </table>
        </div>
        
        <!-- SEÇÃO: POSIÇÕES EM ABERTO -->
        <div class="section">
            <div class="section-title">⏳ Posições em Aberto (Aguardando Resolução)</div>
            <table id="abertos-table">
                <thead>
                    <tr>
                        <th>Cidade</th>
                        <th>Data</th>
                        <th>Aposta</th>
                        <th>Pergunta</th>
                        <th>Probabilidade</th>
                    </tr>
                </thead>
                <tbody id="abertos-body"></tbody>
            </table>
            <div id="sem-abertos" class="info-box" style="display:none; border-left-color: #00ff88;">
                ✅ Nenhuma posição aberta! Aguardando próximos trades...
            </div>
        </div>
        
        <!-- SEÇÃO: TRADES RECENTES -->
        <div class="section">
            <div class="section-title">📝 Trades Recentes (Últimos 10)</div>
            <table id="recentes-table">
                <thead>
                    <tr>
                        <th>Resultado</th>
                        <th>Cidade</th>
                        <th>Data</th>
                        <th>Aposta</th>
                        <th>Lucro/Prejuízo</th>
                        <th>Pergunta</th>
                    </tr>
                </thead>
                <tbody id="recentes-body"></tbody>
            </table>
        </div>
        
        <div class="timestamp">
            Atualizado: <span id="timestamp">-</span> | Refresh automático a cada 10 segundos
        </div>
    </div>
    
    <script>
        function atualizar() {
            fetch('/api/stats')
                .then(r => r.json())
                .then(data => {
                    // Cards principais
                    document.getElementById('saldo').textContent = '$' + data.saldo.toFixed(2);
                    document.getElementById('pnl').textContent = '$' + data.pnl_total.toFixed(2);
                    document.getElementById('pnl').className = data.pnl_total >= 0 ? 'valor positivo' : 'valor negativo';
                    document.getElementById('taxa').textContent = data.taxa_vitoria.toFixed(1) + '%';
                    document.getElementById('abertos').textContent = data.abertos;
                    document.getElementById('exposicao').textContent = 'Exposição: $' + data.exposicao_aberta.toFixed(2);
                    
                    // Stats
                    document.getElementById('total_fechados').textContent = data.total_fechados;
                    document.getElementById('ganhos').textContent = data.ganhos;
                    document.getElementById('perdidos').textContent = data.perdidos;
                    document.getElementById('abertos2').textContent = data.abertos;
                    
                    // Por cidade
                    let cidades_html = '';
                    for (let [cidade, stats] of Object.entries(data.por_cidade)) {
                        cidades_html += `
                            <tr>
                                <td>${cidade}</td>
                                <td class="win">${stats.ganhos}</td>
                                <td class="loss">${stats.perdas}</td>
                                <td class="${stats.pnl >= 0 ? 'win' : 'loss'}">$${stats.pnl.toFixed(2)}</td>
                            </tr>
                        `;
                    }
                    document.getElementById('cidades-body').innerHTML = cidades_html;
                    
                    // Posições em aberto
                    if (data.em_aberto.length === 0) {
                        document.getElementById('sem-abertos').style.display = 'block';
                        document.getElementById('abertos-table').style.display = 'none';
                    } else {
                        document.getElementById('sem-abertos').style.display = 'none';
                        document.getElementById('abertos-table').style.display = 'table';
                        let abertos_html = '';
                        for (let t of data.em_aberto) {
                            abertos_html += `
                                <tr>
                                    <td>${t.cidade}</td>
                                    <td>${t.data}</td>
                                    <td>$${t.stake.toFixed(2)}</td>
                                    <td>${t.pergunta}</td>
                                    <td>${(t.probabilidade * 100).toFixed(1)}%</td>
                                </tr>
                            `;
                        }
                        document.getElementById('abertos-body').innerHTML = abertos_html;
                    }
                    
                    // Recentes
                    let recentes_html = '';
                    for (let t of data.recentes) {
                        let classe = t.resultado.includes('WIN') ? 'win' : 'loss';
                        recentes_html += `
                            <tr>
                                <td class="${classe}">${t.resultado}</td>
                                <td>${t.cidade}</td>
                                <td>${t.data}</td>
                                <td>$${t.stake.toFixed(2)}</td>
                                <td class="${classe}">$${t.pnl > 0 ? '+' : ''}${t.pnl.toFixed(2)}</td>
                                <td>${t.pergunta}</td>
                            </tr>
                        `;
                    }
                    document.getElementById('recentes-body').innerHTML = recentes_html;
                    
                    // Timestamp
                    let hora = new Date(data.atualizado).toLocaleTimeString('pt-BR');
                    document.getElementById('timestamp').textContent = hora;
                })
                .catch(e => console.error('Erro:', e));
        }
        
        atualizar();
        setInterval(atualizar, 10000);
    </script>
</body>
</html>
"""

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML.encode('utf-8'))
        elif self.path == '/api/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            bankroll = load_data()
            stats = calcular_stats(bankroll)
            self.wfile.write(json.dumps(stats).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    with socketserver.TCPServer(('', PORT), Handler) as s:
        print(f"\n✅ Dashboard aberto em: http://localhost:{PORT}")
        print(f"📊 Atualizando a cada 10 segundos\n")
        try:
            s.serve_forever()
        except KeyboardInterrupt:
            print("\n❌ Encerrado")
