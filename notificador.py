import os
import json
import time
import requests
import subprocess

from threading import Thread

from config import (
    TELEGRAM_TOKEN,
    CHAT_ID,
    MAX_POSITION,
    KELLY_FRACTION
)

# =========================================================
# CONFIG
# =========================================================

BOT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

TELEGRAM_API = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
)

BANKROLL_PATH = os.path.join(
    BOT_DIR,
    "bankroll.json"
)

# =========================================================
# TELEGRAM
# =========================================================

def enviar_mensagem(
    texto,
    parse_mode="HTML"
):

    if not TELEGRAM_TOKEN or not CHAT_ID:

        print(
            "Telegram não configurado"
        )

        return False

    try:

        r = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": texto,
                "parse_mode": parse_mode
            },
            timeout=15
        )

        return r.status_code == 200

    except Exception as e:

        print(
            f"Erro Telegram: {e}"
        )

        return False

# =========================================================
# LOAD BANKROLL
# =========================================================

def _load_bankroll():

    try:

        with open(
            BANKROLL_PATH,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        print(
            f"Erro bankroll: {e}"
        )

        return {
            "balance": 0,
            "history": []
        }

# =========================================================
# KELLY
# =========================================================

def _kelly_math(
    balance,
    model_prob,
    market_price
):

    p = model_prob

    q = 1 - p

    b = (
        (1 / market_price) - 1
        if market_price > 0 else 0
    )

    f_puro = (
        max((p * b - q) / b, 0)
        if b > 0 else 0
    )

    f_half = (
        f_puro * KELLY_FRACTION
    )

    f_cap = min(
        f_half,
        MAX_POSITION
    )

    stake = round(
        balance * f_cap,
        2
    )

    return {
        "stake": stake,
        "kelly_pct": round(
            f_half * 100,
            1
        )
    }

# =========================================================
# NOTIFICAÇÃO TRADE
# =========================================================

def notificar_entrada_trade(
    city,
    market_date,
    target,
    unit,
    stake,
    model_prob,
    market_price,
    edge,
    balance=None,
    shares=None
):

    ev_pct = (
        round(
            (
                model_prob /
                market_price - 1
            ) * 100,
            1
        )
        if market_price > 0 else 0
    )

    texto = (
        f"<b>🚨 NOVO TRADE</b>\n\n"
        f"<b>Cidade:</b> {city}\n"
        f"<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Stake:</b> ${stake:.2f}\n\n"
        f"<b>Modelo:</b> "
        f"{model_prob*100:.1f}%\n"
        f"<b>Mercado:</b> "
        f"{market_price*100:.1f}%\n"
        f"<b>Edge:</b> "
        f"+{edge:.1f}%\n"
        f"<b>EV:</b> "
        f"+{ev_pct:.1f}%"
    )

    if balance:

        km = _kelly_math(
            balance,
            model_prob,
            market_price
        )

        texto += (
            f"\n\n<b>Kelly</b>\n"
            f"Half Kelly: "
            f"{km['kelly_pct']}%"
        )

    enviar_mensagem(texto)

# =========================================================
# CONTEXTO IA
# =========================================================

def _build_context():

    bankroll = _load_bankroll()

    history = bankroll.get(
        "history",
        []
    )

    balance = bankroll.get(
        "balance",
        0
    )

    abertos = [
        t for t in history
        if t.get("result") == "OPEN"
    ]

    fechados = [
        t for t in history
        if t.get("result")
        in ("WIN", "LOSS")
    ]

    wins = [
        t for t in fechados
        if t.get("result") == "WIN"
    ]

    losses = [
        t for t in fechados
        if t.get("result") == "LOSS"
    ]

    pnl = sum(
        t.get("pnl", 0)
        for t in fechados
    )

    wr = (
        round(
            len(wins)
            / len(fechados)
            * 100,
            1
        )
        if fechados else 0
    )

    exposicao = sum(
        t.get("stake", 0)
        for t in abertos
    )

    trades_abertos = ""

    for t in abertos[:25]:

        trades_abertos += (
            f"\n"
            f"- Cidade: {t.get('city')}\n"
            f"  Data: {t.get('market_date')}\n"
            f"  Stake: ${t.get('stake',0):.2f}\n"
            f"  Modelo: {t.get('model_prob',0)*100:.1f}%\n"
            f"  Mercado: {t.get('market_price',0)*100:.1f}%\n"
            f"  Edge: {t.get('edge',0):+.1f}%\n"
        )

    trades_fechados = ""

    for t in fechados[-30:]:

        trades_fechados += (
            f"\n"
            f"- Cidade: {t.get('city')}\n"
            f"  Resultado: {t.get('result')}\n"
            f"  Stake: ${t.get('stake',0):.2f}\n"
            f"  PnL: ${t.get('pnl',0):+.2f}\n"
            f"  Modelo: {t.get('model_prob',0)*100:.1f}%\n"
            f"  Mercado: {t.get('market_price',0)*100:.1f}%\n"
        )

    return f"""
Você é o analista oficial do WEATHER QUANT.

O WEATHER QUANT é um sistema quantitativo
de probabilidades climáticas.

Você NÃO é um assistente genérico.

Você DEVE responder como:
- trader quantitativo
- analista estatístico
- especialista em probabilidades
- especialista em weather markets

Você possui acesso COMPLETO
aos dados reais do bot abaixo.

===================================
STATUS GERAL
===================================

Saldo: ${balance:.2f}

PnL Total: ${pnl:+.2f}

Win Rate: {wr}%

Wins: {len(wins)}

Losses: {len(losses)}

Trades abertos: {len(abertos)}

Exposição: ${exposicao:.2f}

===================================
TRADES ABERTOS
===================================

{trades_abertos if trades_abertos else "Nenhum"}

===================================
ÚLTIMOS TRADES FECHADOS
===================================

{trades_fechados if trades_fechados else "Nenhum"}

===================================
REGRAS
===================================

- Responda SEMPRE em português.
- Seja analítico.
- Use os dados reais acima.
- Nunca diga que não possui acesso.
- Nunca diga que é IA genérica.
- Fale como gestor quantitativo.
- Máximo 4 parágrafos.
"""

# =========================================================
# GROQ
# =========================================================

def _perguntar_ia(
    pergunta_usuario
):

    contexto = _build_context()

    groq_key = os.environ.get(
        "GROQ_API_KEY",
        ""
    )

    if not groq_key:

        return (
            "❌ GROQ_API_KEY não configurada."
        )

    try:

        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization":
                f"Bearer {groq_key}",
                "Content-Type":
                "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {
                        "role": "system",
                        "content": contexto
                    },
                    {
                        "role": "user",
                        "content": pergunta_usuario
                    }
                ],
                "temperature": 0.4,
                "max_tokens": 700
            },
            timeout=45
        )

        print("\n===== GROQ DEBUG =====")
        print("STATUS:", r.status_code)
        print("TEXT:", r.text[:2000])
        print("======================\n")

        try:

            data = r.json()

        except Exception:

            return (
                "❌ Resposta inválida:\n\n"
                f"{r.text[:500]}"
            )

        if (
            r.status_code == 200
            and "choices" in data
        ):

            return (
                data["choices"][0]
                ["message"]["content"]
            )

        return (
            f"❌ Erro API:\n\n"
            f"{data}"
        )

    except requests.exceptions.Timeout:

        return (
            "⏱️ Timeout da IA."
        )

    except Exception as e:

        return (
            f"❌ Erro:\n\n"
            f"{str(e)}"
        )

# =========================================================
# COMANDOS
# =========================================================

def processar_comando(
    texto
):

    cmd = texto.lower().strip()

    if cmd == "/help":

        enviar_mensagem(
            "<b>COMANDOS</b>\n\n"
            "/status\n"
            "/settlement\n"
            "/help\n\n"
            "💬 Você pode conversar livremente."
        )

    elif cmd == "/status":

        bankroll = _load_bankroll()

        balance = bankroll.get(
            "balance",
            0
        )

        history = bankroll.get(
            "history",
            []
        )

        abertos = [
            t for t in history
            if t.get("result") == "OPEN"
        ]

        enviar_mensagem(
            f"<b>STATUS</b>\n\n"
            f"Saldo: ${balance:.2f}\n"
            f"Trades abertos: {len(abertos)}"
        )

    elif cmd == "/settlement":

        enviar_mensagem(
            "Executando settlement..."
        )

        try:

            res = subprocess.run(
                [
                    "python",
                    "settlement.py"
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=BOT_DIR,
            )

            if res.returncode == 0:

                enviar_mensagem(
                    "✅ Settlement executado."
                )

            else:

                enviar_mensagem(
                    f"Erro:\n\n"
                    f"{res.stderr[:1500]}"
                )

        except Exception as e:

            enviar_mensagem(
                str(e)
            )

    else:

        resposta = _perguntar_ia(
            texto
        )

        enviar_mensagem(
            resposta
        )

# =========================================================
# LISTENER
# =========================================================

def iniciar_listener():

    def listen():

        offset = 0

        print(
            "Listener iniciado"
        )

        while True:

            try:

                r = requests.get(
                    f"{TELEGRAM_API}/getUpdates",
                    params={
                        "offset": offset,
                        "timeout": 30
                    },
                    timeout=35
                )

                if r.status_code == 200:

                    dados = r.json()

                    for update in dados.get(
                        "result",
                        []
                    ):

                        offset = (
                            update["update_id"]
                            + 1
                        )

                        texto = (
                            update.get(
                                "message",
                                {}
                            ).get(
                                "text",
                                ""
                            )
                        )

                        if texto:

                            print(
                                f"Telegram: {texto}"
                            )

                            processar_comando(
                                texto
                            )

                time.sleep(1)

            except Exception as e:

                print(
                    f"Erro listener: {e}"
                )

                time.sleep(5)

    Thread(
        target=listen,
        daemon=True
    ).start()

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print(
        "Testando Telegram..."
    )

    ok = enviar_mensagem(
        "✅ WEATHER QUANT online."
    )

    print(
        "OK"
        if ok else "Falhou"
    )
