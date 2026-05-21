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

# =========================================================
# TELEGRAM
# =========================================================

def enviar_mensagem(
    texto,
    parse_mode="HTML"
):

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram não configurado")
        return False

    try:

        r = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": texto,
                "parse_mode": parse_mode
            },
            timeout=10
        )

        return r.status_code == 200

    except Exception as e:

        print(f"Erro Telegram: {e}")

        return False

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
# TRADE
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

    msg = (
        f"<b>NOVO TRADE</b>\n\n"
        f"<b>Cidade:</b> {city}\n"
        f"<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Stake:</b> ${stake:.2f}\n\n"
        f"Modelo: "
        f"<b>{model_prob*100:.1f}%</b>\n"
        f"Mercado: "
        f"<b>{market_price*100:.1f}%</b>\n"
        f"Edge: "
        f"<b>+{edge:.1f}%</b>\n"
        f"EV: "
        f"<b>+{ev_pct:.1f}%</b>"
    )

    if balance:

        km = _kelly_math(
            balance,
            model_prob,
            market_price
        )

        msg += (
            f"\n\n<b>Kelly</b>\n"
            f"Half Kelly: "
            f"{km['kelly_pct']}%"
        )

    enviar_mensagem(msg)

# =========================================================
# IA CONTEXTO
# =========================================================

def _build_context():

    try:

        with open(
            os.path.join(
                BOT_DIR,
                "bankroll.json"
            ),
            "r",
            encoding="utf-8"
        ) as f:

            bankroll = json.load(f)

    except Exception:

        bankroll = {
            "balance": 0,
            "history": []
        }

    history = bankroll.get(
        "history",
        []
    )

    balance = bankroll.get(
        "balance",
        0
    )

    fechados = [
        t for t in history
        if t.get("result")
        in ("WIN", "LOSS")
    ]

    wins = [
        t for t in fechados
        if t.get("result") == "WIN"
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

    return f"""
BOT WEATHER QUANT

Saldo: ${balance:.2f}
PnL: ${pnl:+.2f}
Win Rate: {wr}%

Responda em português.
"""

# =========================================================
# GROQ IA
# =========================================================

def _perguntar_grok(
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
                "temperature": 0.7,
                "max_tokens": 500
            },
            timeout=30
        )

        print("\n===== GROQ DEBUG =====")
        print("STATUS:", r.status_code)
        print("TEXT:", r.text[:1000])
        print("======================\n")

        try:

            data = r.json()

        except Exception:

            return (
                "❌ Resposta inválida:\n\n"
                f"{r.text[:300]}"
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
            "⏱️ Timeout da API."
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

        enviar_mensagem(
            "✅ Bot online."
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
                timeout=60,
                cwd=BOT_DIR,
            )

            if res.returncode == 0:

                enviar_mensagem(
                    "✅ Settlement executado."
                )

            else:

                enviar_mensagem(
                    f"Erro:\n\n"
                    f"{res.stderr}"
                )

        except Exception as e:

            enviar_mensagem(
                str(e)
            )

    else:

        resposta = _perguntar_grok(
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

                            print(texto)

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
        "✅ Notificador iniciado!"
    )

    print(
        "OK"
        if ok else "Falhou"
    )
