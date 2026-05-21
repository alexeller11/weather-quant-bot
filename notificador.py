"""
NOTIFICADOR TELEGRAM — WEATHER QUANT
Notificações automáticas + IA Grok para conversa natural.
"""

import os
import requests
import json
import subprocess
import time
from threading import Thread

from config import TELEGRAM_TOKEN, CHAT_ID, MAX_POSITION, KELLY_FRACTION

BOT_DIR = os.path.dirname(os.path.abspath(__file__))

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# ──────────────────────────────────────────────────────────────
# ENVIO BASE
# ──────────────────────────────────────────────────────────────

def enviar_mensagem(texto, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Telegram: token ou chat_id não configurados")
        return False

    try:
        r = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": texto,
                "parse_mode": parse_mode
            },
            timeout=10,
        )

        return r.status_code == 200

    except Exception as e:
        print(f"⚠️ Telegram erro: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# KELLY MATH HELPER
# ──────────────────────────────────────────────────────────────

def _kelly_math(balance, model_prob, market_price):
    p = model_prob
    q = 1.0 - model_prob

    b = (1.0 / market_price) - 1.0 if market_price > 0 else 0

    f_puro = max((p * b - q) / b, 0.0) if b > 0 else 0.0

    f_half = f_puro * KELLY_FRACTION

    f_cap = min(f_half, MAX_POSITION)

    stake_t = round(balance * f_cap, 2)

    shares = int(stake_t / market_price) if market_price > 0 else 0

    custo = round(shares * market_price, 2)

    desp = (
        round((1 - custo / stake_t) * 100, 1)
        if stake_t > 0 else 0
    )

    ev_pct = (
        round((p / market_price - 1) * 100, 1)
        if market_price > 0 else 0
    )

    return {
        "kelly_puro_pct": round(f_puro * 100, 1),
        "half_kelly_pct": round(f_half * 100, 1),
        "cap_pct": int(round(MAX_POSITION * 100, 0)),
        "ev_pct": ev_pct,
        "stake_teorico": stake_t,
        "custo_real": custo,
        "desperdicio_pct": desp,
    }


# ──────────────────────────────────────────────────────────────
# TABELA DE VALIDAÇÃO
# ──────────────────────────────────────────────────────────────

def _tabela_validacao(target, unit, model_prob, real_temp_c, resultado):

    if model_prob is None or real_temp_c is None:
        return ""

    if str(unit).upper() == "F":

        real_val = real_temp_c * 9 / 5 + 32

        real_str = f"{real_temp_c:.1f}C = {real_val:.1f}F"

        tgt_str = f"{target}F"

        acertou = abs(real_val - float(target)) < 0.6

    else:

        real_val = real_temp_c

        real_str = f"{real_temp_c:.1f}C"

        tgt_str = f"{target}C"

        acertou = abs(real_temp_c - float(target)) < 0.5

    icone_t = (
        "EXATO"
        if acertou else (
            "CORRETO"
            if resultado == "WIN"
            else "ERRADO"
        )
    )

    icone_p = (
        "CORRETO"
        if resultado == "WIN"
        else "ERRADO"
    )

    brier = round(
        (
            model_prob -
            (
                1.0 if resultado == "WIN"
                else 0.0
            )
        ) ** 2,
        4
    )

    b_label = (
        "Excelente"
        if brier < 0.1
        else (
            "Bom"
            if brier < 0.25
            else "Ruim"
        )
    )

    return (
        f"\n\n<b>Validacao</b>\n"
        f"<pre>"
        f"Temp    | {tgt_str:<8} | {real_str} | {icone_t}\n"
        f"Modelo  | {model_prob*100:.0f}%      | {icone_p}\n"
        f"Brier   | --       | {brier} ({b_label})"
        f"</pre>"
    )


# ──────────────────────────────────────────────────────────────
# NOTIFICAÇÕES DE TRADE
# ──────────────────────────────────────────────────────────────

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
        round((model_prob / market_price - 1) * 100, 1)
        if market_price > 0 else 0
    )

    shares_ln = (
        f"\n<b>Shares:</b> {shares}"
        if shares is not None else ""
    )

    kelly_block = ""

    if balance is not None and balance > 0:

        km = _kelly_math(balance, model_prob, market_price)

        kelly_block = (
            f"\n\n<b>Matematica Kelly</b>\n"
            f"Kelly puro: <b>{km['kelly_puro_pct']}%</b> | "
            f"Half-Kelly: <b>{km['half_kelly_pct']}%</b> | "
            f"Cap: <b>{km['cap_pct']}%</b>\n"
            f"Teorico: ${km['stake_teorico']:.2f} → "
            f"Real: ${km['custo_real']:.2f}"
        )

        if km["desperdicio_pct"] > 5:
            kelly_block += (
                f" ({km['desperdicio_pct']}% perdido)"
            )

    enviar_mensagem(
        f"<b>NOVO TRADE</b>\n\n"
        f"<b>Cidade:</b> {city}\n"
        f"<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> <b>${stake:.2f}</b>{shares_ln}\n\n"
        f"Modelo: <b>{model_prob*100:.1f}%</b> | "
        f"Mercado: <b>{market_price*100:.1f}%</b>\n"
        f"Edge: <b>+{edge:.1f}%</b> | "
        f"EV: <b>+{ev_pct:.1f}%</b>"
        f"{kelly_block}\n\n"
        f"Aguardando resolucao..."
    )


def notificar_settlement_win(
    city,
    market_date,
    target,
    unit,
    stake,
    pnl,
    saldo,
    model_prob=None,
    real_temp_c=None
):

    tabela = _tabela_validacao(
        target,
        unit,
        model_prob,
        real_temp_c,
        "WIN"
    )

    enviar_mensagem(
        f"<b>VITORIA!</b>\n\n"
        f"<b>Cidade:</b> {city} | "
        f"<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> ${stake:.2f} | "
        f"<b>Ganho: +${pnl:.2f}</b>"
        f"{tabela}\n\n"
        f"Saldo: <b>${saldo:.2f}</b>"
    )


def notificar_settlement_loss(
    city,
    market_date,
    target,
    unit,
    stake,
    pnl,
    saldo,
    model_prob=None,
    real_temp_c=None
):

    tabela = _tabela_validacao(
        target,
        unit,
        model_prob,
        real_temp_c,
        "LOSS"
    )

    enviar_mensagem(
        f"<b>DERROTA</b>\n\n"
        f"<b>Cidade:</b> {city} | "
        f"<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> ${stake:.2f} | "
        f"<b>Perda: -${abs(pnl):.2f}</b>"
        f"{tabela}\n\n"
        f"Saldo: <b>${saldo:.2f}</b>"
    )


# ──────────────────────────────────────────────────────────────
# IA — GROK
# ──────────────────────────────────────────────────────────────

def _build_context():

    try:
        bankroll_path = os.path.join(
            BOT_DIR,
            "bankroll.json"
        )

        with open(bankroll_path, "r", encoding="utf-8") as f:
            bankroll = json.load(f)

    except Exception:
        bankroll = {
            "balance": 0,
            "history": []
        }

    history = bankroll.get("history", [])

    balance = bankroll.get("balance", 0)

    abertos = [
        t for t in history
        if t.get("result") == "OPEN"
    ]

    fechados = [
        t for t in history
        if t.get("result") in ("WIN", "LOSS")
    ]

    wins = [
        t for t in fechados
        if t.get("result") == "WIN"
    ]

    pnl = sum(
        t.get("pnl", 0)
        for t in fechados
    )

    win_rate = (
        round(len(wins) / len(fechados) * 100, 1)
        if fechados else 0
    )

    exposicao = sum(
        t.get("stake", 0)
        for t in abertos
    )

    return f"""
BOT WEATHER QUANT

Saldo: ${balance:.2f}
PnL: ${pnl:+.2f}
Win rate: {win_rate}%
Trades abertos: {len(abertos)}
Exposição: ${exposicao:.2f}

Responda em português de forma curta e objetiva.
"""


def _perguntar_grok(pergunta_usuario):

    contexto = _build_context()

    grok_key = (
        os.environ.get("GROK_API_KEY")
        or os.environ.get("GROQ_API_KEY")
        or ""
    )

    if not grok_key:
        return (
            "❌ Nenhuma chave configurada!\n\n"
            "Adicione GROK_API_KEY no Railway."
        )

    try:

        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {grok_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-2",
                "max_tokens": 600,
                "messages": [
                    {
                        "role": "system",
                        "content": contexto
                    },
                    {
                        "role": "user",
                        "content": pergunta_usuario
                    },
                ],
            },
            timeout=30,
        )

        data = r.json()

        if r.status_code == 200:
            return data["choices"][0]["message"]["content"]

        erro = data.get(
            "error",
            {}
        ).get(
            "message",
            str(data)
        )

        return f"❌ Erro Grok {r.status_code}: {erro}"

    except requests.exceptions.Timeout:

        return (
            "⏱️ Timeout — Grok demorou muito "
            "para responder."
        )

    except Exception as e:

        return (
            f"❌ Erro ao conectar com Grok: "
            f"{str(e)}"
        )


# ──────────────────────────────────────────────────────────────
# COMANDOS TELEGRAM
# ──────────────────────────────────────────────────────────────

def processar_comando(texto):

    cmd = texto.lower().strip()

    if cmd == "/help":

        enviar_mensagem(
            "<b>COMANDOS</b>\n\n"
            "/status\n"
            "/settlement\n"
            "/help\n\n"
            "💬 Pode conversar livremente com o bot."
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
                ["python", "settlement.py"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=BOT_DIR,
            )

            if res.returncode == 0:

                enviar_mensagem(
                    "✅ Settlement executado!"
                )

            else:

                erro = (
                    res.stderr[:400]
                    if res.stderr
                    else "sem detalhes"
                )

                enviar_mensagem(
                    f"❌ Erro:\n<pre>{erro}</pre>"
                )

        except Exception as e:

            enviar_mensagem(
                f"❌ {e}"
            )

    else:

        resposta = _perguntar_grok(texto)

        enviar_mensagem(resposta)


# ──────────────────────────────────────────────────────────────
# LISTENER
# ──────────────────────────────────────────────────────────────

def iniciar_listener():

    def listen():

        offset = 0

        print("Listener Telegram iniciado...")

        while True:

            try:

                r = requests.get(
                    f"{TELEGRAM_API}/getUpdates",
                    params={
                        "offset": offset,
                        "timeout": 30
                    },
                    timeout=35,
                )

                if r.status_code == 200:

                    dados = r.json()

                    if (
                        dados.get("ok")
                        and dados.get("result")
                    ):

                        for update in dados["result"]:

                            offset = (
                                update["update_id"] + 1
                            )

                            msg = update.get(
                                "message",
                                {}
                            )

                            texto = msg.get(
                                "text",
                                ""
                            ).strip()

                            if texto:

                                print(
                                    f"Telegram: "
                                    f"{texto[:60]}"
                                )

                                processar_comando(texto)

                time.sleep(1)

            except Exception as e:

                print(f"Listener erro: {e}")

                time.sleep(5)

    Thread(
        target=listen,
        daemon=True
    ).start()


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":

    print("Testando Telegram...")

    ok = enviar_mensagem("✅ Notificador OK!")

    print("OK" if ok else "Falhou")
