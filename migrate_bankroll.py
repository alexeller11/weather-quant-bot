"""
migrate_bankroll.py — Importa um bankroll inicial para o PostgreSQL.
Execute UMA VEZ após configurar DATABASE_URL no Railway.

⚠️  ATENÇÃO: O bankroll hardcoded neste arquivo é um SNAPSHOT HISTÓRICO
    com saldo $21.16 (estado em ~22/05/2026). Se o banco já tiver dados
    mais recentes, NÃO rode este script — ele vai sobrescrever o bankroll
    real de produção com dados antigos e causar perda de histórico.

    Uso correto: somente para inicializar um banco PostgreSQL vazio pela
    primeira vez, em ambiente de teste ou após reset intencional.

Uso:
    DATABASE_URL=postgres://... python migrate_bankroll.py
"""

import os
import json
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("❌ DATABASE_URL não configurada.")
    exit(1)

# ⚠️  SNAPSHOT DESATUALIZADO — saldo $21.16, estado em ~2026-05-22.
# Este dado é histórico e NÃO reflete o bankroll atual de produção.
# Só use para inicializar um banco VAZIO em ambiente de teste.
BANKROLL = {
    "balance": 21.16580000000001,
    "history": [
        {"market_id":"2289758","city":"Tokyo","question":"Will the highest temperature in Tokyo be 27°C or higher on May 20?","market_date":"2026-05-20","entry_time":"2026-05-19T22:13:32.195546","exit_time":"2026-05-20T00:55:06.931204","type":"ABOVE","unit":"C","target":27.0,"shares":2,"forecast_day":1,"model_prob":0.99,"market_price":0.875,"edge":0.115,"ev":0.1314,"stake":1.75,"result":"WIN","pnl":0.25,"fee":0.01,"real_temp_c":30.7},
        {"market_id":"2299681","city":"Los Angeles","question":"Will the highest temperature in Los Angeles be 74°F or higher on May 21?","market_date":"2026-05-21","entry_time":"2026-05-19T22:13:41.312375","exit_time":"2026-05-21T00:33:06.686474","type":"ABOVE","unit":"F","target":74.0,"shares":8,"forecast_day":2,"model_prob":0.99,"market_price":0.28,"edge":0.71,"ev":2.5357,"stake":2.24,"result":"WIN","pnl":5.64,"fee":0.12,"real_temp_c":30.5},
        {"market_id":"2299353","city":"Seoul","question":"Will the highest temperature in Seoul be 18°C on May 21?","market_date":"2026-05-21","entry_time":"2026-05-20T14:04:32.276444","exit_time":"2026-05-22T01:35:36.815568","type":"EXACT","unit":"C","target":18.0,"target_high":None,"shares":123,"forecast_day":1,"model_prob":0.6884,"market_price":0.039,"edge":0.6494,"ev":16.6513,"stake":4.8,"result":"LOSS","pnl":-4.8,"fee":0.0,"real_temp_c":19.5},
        {"market_id":"2299354","city":"Seoul","question":"Will the highest temperature in Seoul be 19°C on May 21?","market_date":"2026-05-21","entry_time":"2026-05-20T14:04:34.621964","exit_time":"2026-05-22T01:35:36.815631","type":"EXACT","unit":"C","target":19.0,"target_high":None,"shares":1,"forecast_day":1,"model_prob":0.2262,"market_price":0.13,"edge":0.0962,"ev":0.74,"stake":0.13,"result":"WIN","pnl":0.85,"fee":0.02,"real_temp_c":19.5},
        {"market_id":"2299321","city":"Paris","question":"Will the highest temperature in Paris be 25°C on May 21?","market_date":"2026-05-21","entry_time":"2026-05-20T19:48:07.002381","exit_time":"2026-05-22T01:35:36.815642","type":"EXACT","unit":"C","target":25.0,"target_high":None,"shares":10,"forecast_day":1,"model_prob":0.7219,"market_price":0.33,"edge":0.3919,"ev":1.1876,"stake":3.3,"result":"LOSS","pnl":-3.3,"fee":0.0,"real_temp_c":22.7},
        {"market_id":"2299507","city":"Hong Kong","question":"Will the highest temperature in Hong Kong be 28°C on May 21?","market_date":"2026-05-21","entry_time":"2026-05-20T19:48:42.799860","exit_time":"2026-05-22T01:35:36.815649","type":"EXACT","unit":"C","target":28.0,"target_high":None,"shares":6,"forecast_day":1,"model_prob":0.2744,"market_price":0.2,"edge":0.0744,"ev":0.372,"stake":1.2,"result":"LOSS","pnl":-1.2,"fee":0.0,"real_temp_c":26.4},
        {"market_id":"2299540","city":"Milan","question":"Will the highest temperature in Milan be 27°C on May 21?","market_date":"2026-05-21","entry_time":"2026-05-20T19:49:03.183236","exit_time":"2026-05-22T01:35:36.815656","type":"EXACT","unit":"C","target":27.0,"target_high":None,"shares":7,"forecast_day":1,"model_prob":0.4864,"market_price":0.36,"edge":0.1264,"ev":0.3511,"stake":2.52,"result":"LOSS","pnl":-2.52,"fee":0.0,"real_temp_c":28.7},
        {"market_id":"2299594","city":"Beijing","question":"Will the highest temperature in Beijing be 27°C on May 21?","market_date":"2026-05-21","entry_time":"2026-05-20T19:50:03.818311","exit_time":"2026-05-22T01:35:36.815667","type":"EXACT","unit":"C","target":27.0,"target_high":None,"shares":6,"forecast_day":1,"model_prob":0.6373,"market_price":0.285,"edge":0.3523,"ev":1.2361,"stake":1.71,"result":"LOSS","pnl":-1.71,"fee":0.0,"real_temp_c":24.4},
        {"market_id":"2299723","city":"Mexico City","question":"Will the highest temperature in Mexico City be 24°C on May 21?","market_date":"2026-05-21","entry_time":"2026-05-20T19:54:04.612950","exit_time":"2026-05-22T01:35:36.815673","type":"EXACT","unit":"C","target":24.0,"target_high":None,"shares":6,"forecast_day":1,"model_prob":0.1764,"market_price":0.095,"edge":0.0814,"ev":0.8568,"stake":0.57,"result":"LOSS","pnl":-0.57,"fee":0.0,"real_temp_c":23.2},
        {"market_id":"2299330","city":"São Paulo","question":"Will the highest temperature in Sao Paulo be 17°C on May 21?","market_date":"2026-05-21","entry_time":"2026-05-20T19:54:35.891138","exit_time":"2026-05-22T01:35:36.815683","type":"EXACT","unit":"C","target":17.0,"target_high":None,"shares":2,"forecast_day":1,"model_prob":0.4075,"market_price":0.335,"edge":0.0725,"ev":0.2164,"stake":0.67,"result":"WIN","pnl":1.3,"fee":0.03,"real_temp_c":16.8},
    ]
}

try:
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bankroll (
                id       SERIAL PRIMARY KEY,
                data     JSONB NOT NULL,
                saved_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("SELECT COUNT(*) FROM bankroll")
        count = cur.fetchone()[0]
        if count > 0:
            print(f"⚠️  Banco já tem {count} registro(s).")
            print("⚠️  ATENÇÃO: isso irá sobrescrever o bankroll real de produção")
            print("    com um snapshot histórico desatualizado ($21.16).")
            print("Deseja continuar? (s/n): ", end="")
            resp = input().strip().lower()
            if resp != "s":
                print("Cancelado.")
                conn.close()
                exit(0)
            cur.execute("DELETE FROM bankroll")
            print("Registros anteriores removidos.")

        cur.execute(
            "INSERT INTO bankroll (data) VALUES (%s)",
            (json.dumps(BANKROLL),)
        )
    conn.commit()
    conn.close()
    print(f"✅ Bankroll importado com sucesso!")
    print(f"   Saldo: ${BANKROLL['balance']:.2f}")
    print(f"   Trades: {len(BANKROLL['history'])}")
    print()
    print("⚠️  Lembre-se: este é um snapshot histórico.")
    print("   Use apenas para inicialização de banco vazio em testes.")
except Exception as e:
    print(f"❌ Erro: {e}")
