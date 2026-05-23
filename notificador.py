"""
NOTIFICADOR TELEGRAM — WEATHER QUANT
Notificações automáticas + IA Grok para conversa natural.
"""

import os
import requests
import json
import subprocess
import time
from datetime import datetime, timezone
from threading import Thread

from config import TELEGRAM_TOKEN, CHAT_ID, MAX_POSITION, KELLY_FRACTION

BOT_DIR      = os.path.dirname(os.path.abspath(__file__))
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ──────────────────────────────────────────────────────────────
# ENVIO BASE
# ──────────────────────────────────────────────────────────────

def enviar_mensagem(texto, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️  Telegram: token ou chat_id não configurados")
        return False
    try:
        r = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": CHAT_ID, "text": texto, "parse_mode": parse_mode},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"⚠️  Telegram erro: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# KELLY MATH HELPER
# ──────────────────────────────────────────────────────────────

def _kelly_math(balance, model_prob, market_price):
    p, q = model_prob, 1.0 - model_prob
    b    = (1.0 / market_price) - 1.0 if market_price > 0 else 0
    f_puro  = max((p * b - q) / b, 0.0) if b > 0 else 0.0
    f_half  = f_puro * KELLY_FRACTION
    f_cap   = min(f_half, MAX_POSITION)
    stake_t = round(balance * f_cap, 2)
    shares  = int(stake_t / market_price) if market_price > 0 else 0
    custo   = round(shares * market_price, 2)
    desp    = round((1 - custo / stake_t) * 100, 1) if stake_t > 0 else 0
    ev_pct  = round((p / market_price - 1) * 100, 1) if market_price > 0 else 0
    return {
        "kelly_puro_pct": round(f_puro * 100, 1),
        "half_kelly_pct": round(f_half * 100, 1),
        "cap_pct":        int(round(MAX_POSITION * 100, 0)),
        "ev_pct":         ev_pct,
        "stake_teorico":  stake_t,
        "custo_real":     custo,
        "desperdicio_pct":desp,
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
        tgt_str  = f"{target}F"
        acertou  = abs(real_val - float(target)) < 0.6
    else:
        real_val = real_temp_c
        real_str = f"{real_temp_c:.1f}C"
        tgt_str  = f"{target}C"
        acertou  = abs(real_temp_c - float(target)) < 0.5
    icone_t = "EXATO" if acertou else ("CORRETO" if resultado=="WIN" else "ERRADO")
    icone_p = "CORRETO" if resultado=="WIN" else "ERRADO"
    brier   = round((model_prob - (1.0 if resultado=="WIN" else 0.0))**2, 4)
    b_label = "Excelente" if brier < 0.1 else ("Bom" if brier < 0.25 else "Ruim")
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

def notificar_entrada_trade(city, market_date, target, unit, stake,
                             model_prob, market_price, edge,
                             balance=None, shares=None):
    """Notifica entrada de novo trade."""
    ev_pct    = round((model_prob / market_price - 1) * 100, 1) if market_price > 0 else 0
    shares_ln = f"\n<b>Shares:</b> {shares}" if shares is not None else ""

    kelly_block = ""
    if balance is not None and balance > 0:
        km = _kelly_math(balance, model_prob, market_price)
        kelly_block = (
            f"\n\n<b>Matematica Kelly</b>\n"
            f"Kelly puro: <b>{km['kelly_puro_pct']}%</b> | "
            f"Half-Kelly: <b>{km['half_kelly_pct']}%</b> | "
            f"Cap: <b>{km['cap_pct']}%</b>\n"
            f"Teorico: ${km['stake_teorico']:.2f} → Real: ${km['custo_real']:.2f}"
        )
        if km["desperdicio_pct"] > 5:
            kelly_block += f" ({km['desperdicio_pct']}% perdido)"

    enviar_mensagem(
        f"<b>NOVO TRADE</b>\n\n"
        f"<b>Cidade:</b> {city}\n"
        f"<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> <b>${stake:.2f}</b>{shares_ln}\n\n"
        f"Modelo: <b>{model_prob*100:.1f}%</b> | "
        f"Mercado: <b>{market_price*100:.1f}%</b>\n"
        f"Edge: <b>+{edge:.1f}%</b> | EV: <b>+{ev_pct:.1f}%</b>"
        f"{kelly_block}\n\n"
        f"Aguardando resolucao..."
    )


def notificar_settlement_win(city, market_date, target, unit, stake, pnl, saldo,
                              model_prob=None, real_temp_c=None):
    """Notifica vitória no settlement."""
    tabela = _tabela_validacao(target, unit, model_prob, real_temp_c, "WIN")
    enviar_mensagem(
        f"<b>VITORIA!</b>\n\n"
        f"<b>Cidade:</b> {city} | <b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> ${stake:.2f} | <b>Ganho: +${pnl:.2f}</b>"
        f"{tabela}\n\nSaldo: <b>${saldo:.2f}</b>"
    )


def notificar_settlement_loss(city, market_date, target, unit, stake, pnl, saldo,
                               model_prob=None, real_temp_c=None):
    """Notifica derrota no settlement."""
    tabela = _tabela_validacao(target, unit, model_prob, real_temp_c, "LOSS")
    enviar_mensagem(
        f"<b>DERROTA</b>\n\n"
        f"<b>Cidade:</b> {city} | <b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> ${stake:.2f} | <b>Perda: -${abs(pnl):.2f}</b>"
        f"{tabela}\n\nSaldo: <b>${saldo:.2f}</b>"
    )


def notificar_settlement_resumo(total_resolved, wins, losses, total_pnl, saldo):
    """Notifica resumo do settlement."""
    taxa  = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0.0
    emoji = "🟢" if total_pnl >= 0 else "🔴"
    enviar_mensagem(
        f"<b>SETTLEMENT CONCLUIDO</b>\n\n"
        f"Resolvidos: {total_resolved} | "
        f"{wins}W / {losses}L | WR: {taxa:.1f}%\n\n"
        f"{emoji} PnL: <b>${total_pnl:+.2f}</b> | Saldo: <b>${saldo:.2f}</b>"
    )


# ──────────────────────────────────────────────────────────────
# IA — GROK COMO ANALISTA DO BOT
# ──────────────────────────────────────────────────────────────

def _build_context():
    """Monta o contexto do bot para o Grok analisar."""
    try:
        from bankroll import load_bankroll
        bankroll = load_bankroll()
    except Exception:
        bankroll = {"balance": 0, "history": []}

    history  = bankroll.get("history", [])
    balance  = bankroll.get("balance", 0)
    abertos  = [t for t in history if t.get("result") == "OPEN"]
    fechados = [t for t in history if t.get("result") in ("WIN","LOSS")]
    wins     = [t for t in fechados if t.get("result") == "WIN"]
    pnl      = sum(t.get("pnl", 0) for t in fechados)
    win_rate = round(len(wins)/len(fechados)*100,1) if fechados else 0
    exposicao = sum(t.get("stake",0) for t in abertos)

    # Top trades fechados
    ultimos = fechados[-5:] if fechados else []
    trades_str = ""
    for t in ultimos:
        trades_str += (
            f"\n- {t.get('city')} {t.get('market_date')} | "
            f"{t.get('result')} | Stake ${t.get('stake',0):.2f} | "
            f"PnL ${t.get('pnl',0):+.2f} | "
            f"Model {t.get('model_prob',0)*100:.0f}% vs Mkt {t.get('market_price',0)*100:.0f}%"
        )

    abertos_str = ""
    for t in abertos[:8]:
        abertos_str += (
            f"\n- {t.get('city')} {t.get('market_date')} | "
            f"Stake ${t.get('stake',0):.2f} | "
            f"Model {t.get('model_prob',0)*100:.0f}% vs Mkt {t.get('market_price',0)*100:.0f}% | "
            f"Edge {t.get('edge',0):+.1f}%"
        )

    validacao_str = ""
    if fechados and any(t.get("model_prob") for t in fechados):
        brier_scores = [
            (t.get("model_prob", 0) - (1.0 if t.get("result") == "WIN" else 0))**2
            for t in fechados if t.get("model_prob")
        ]
        if brier_scores:
            brier_mean = round(sum(brier_scores) / len(brier_scores), 4)
            validacao_str = f"\n- Brier Score médio: {brier_mean}"

    return f"""CONTEXTO DO BOT DE APOSTA — WEATHER QUANTITATIVO:

SITUACAO ATUAL:
- Saldo: ${balance:.2f}
- PnL total: ${pnl:+.2f}
- Win rate: {win_rate}% ({len(wins)}W/{len(fechados)-len(wins)}L)
- Trades abertos: {len(abertos)} (exposição ${exposicao:.2f})
- Total fechados: {len(fechados)}{validacao_str}

TRADES ABERTOS:{abertos_str if abertos_str else ' Nenhum'}

ÚLTIMOS TRADES FECHADOS:{trades_str if trades_str else ' Nenhum'}

SOBRE O BOT:
- Usa ensemble meteorológico Open-Meteo (50 membros) para calcular probabilidades
- Aposta quando edge (modelo - mercado) > 5%
- Kelly fraction 0.5 (half-Kelly), cap $10 por trade
- Settlement automático às 08:00 e 20:00 UTC
- 1 trade por evento (cidade+data) — sem múltiplos buckets

Responda de forma concisa e direta em português. Seja analítico, honesto sobre riscos e 
baseie suas análises nos dados reais acima. Máximo 3 parágrafos."""


def _perguntar_grok(pergunta_usuario):
    """
    Envia pergunta EXCLUSIVAMENTE para Grok (xAI).
    FIX #6: Timeout robusto e tratamento de erro.
    """
    contexto = _build_context()
    
    grok_key = os.environ.get("GROQ_API_KEY", "")
    
    if not grok_key:
        return "❌ GROQ_API_KEY não configurada!\n\nAdicione a variável de ambiente com sua chave Groq."
    
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {grok_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 600,
                "messages": [
                    {"role": "system", "content": contexto},
                    {"role": "user",   "content": pergunta_usuario},
                ],
            },
            timeout=30,  # FIX: Timeout explícito
        )
        
        if r.status_code == 200:
            data = r.json()
            return data["choices"][0]["message"]["content"]
        else:
            data = r.json() if r.text else {}
            erro = data.get("error", {}).get("message", "erro desconhecido") if isinstance(data, dict) else str(data)
            return f"❌ Erro Grok {r.status_code}: {erro}"
            
    except requests.exceptions.Timeout:
        return "⏱️  Timeout — Grok demorou muito para responder. Tente novamente."
    except requests.exceptions.ConnectionError as e:
        return f"❌ Falha de conexão com Grok: {str(e)[:100]}"
    except Exception as e:
        return f"❌ Erro ao conectar com Grok: {str(e)[:200]}"


# Aliases para compatibilidade
_perguntar_ia = _perguntar_grok
_perguntar_claude = _perguntar_grok


# ──────────────────────────────────────────────────────────────
# COMANDOS DO TELEGRAM
# ──────────────────────────────────────────────────────────────

def processar_comando(texto):
    cmd = texto.lower().strip()

    if cmd == "/settlement":
        enviar_mensagem("Executando settlement...")
        try:
            res = subprocess.run(
                ["python", "settlement.py"],
                capture_output=True, text=True, timeout=60, cwd=BOT_DIR,
            )
            if res.returncode == 0:
                enviar_mensagem("Settlement executado!")
            else:
                erro = res.stderr[:400] if res.stderr else "sem detalhes"
                enviar_mensagem(f"Erro no settlement:\n<pre>{erro}</pre>")
        except subprocess.TimeoutExpired:
            enviar_mensagem("Timeout no settlement (>60s)")
        except Exception as e:
            enviar_mensagem(f"Erro: {e}")

    elif cmd == "/status":
        try:
            from bankroll import load_bankroll
            data = load_bankroll()
            saldo    = data.get("balance", 0)
            history  = data.get("history", [])
            abertos  = [t for t in history if t.get("result") == "OPEN"]
            fechados = [t for t in history if t.get("result") in ("WIN","LOSS")]
            wins     = [t for t in fechados if t.get("result") == "WIN"]
            taxa     = round(len(wins)/len(fechados)*100,1) if fechados else 0
            pnl      = sum(t.get("pnl",0) for t in fechados)
            expo     = sum(t.get("stake",0) for t in abertos)
            emoji    = "🟢" if pnl >= 0 else "🔴"

            det = "".join(
                f"\n  • {t.get('city','?')} {t.get('market_date','?')} "
                f"${t.get('stake',0):.2f} @ {t.get('model_prob',0)*100:.0f}%"
                for t in abertos[:6]
            )

            enviar_mensagem(
                f"<b>STATUS</b>\n\n"
                f"Saldo: <b>${saldo:.2f}</b> | Exposicao: ${expo:.2f}\n"
                f"Abertos: {len(abertos)}{det}\n"
                f"Fechados: {len(fechados)} ({len(wins)}W/{len(fechados)-len(wins)}L)\n"
                f"Win rate: {taxa}%\n"
                f"{emoji} PnL: <b>${pnl:+.2f}</b>"
            )
        except Exception as e:
            enviar_mensagem(f"Erro ao ler status: {e}")

    elif cmd == "/validacao":
        try:
            from validacao import gerar_relatorio
            gerar_relatorio(enviar_telegram=True)
        except Exception as e:
            enviar_mensagem(f"Erro na validacao: {e}")

    elif cmd == "/help":
        enviar_mensagem(
            "<b>COMANDOS</b>\n\n"
            "/status     — Saldo e trades abertos\n"
            "/validacao  — Relatorio de validacao do modelo\n"
            "/settlement — Rodar settlement agora\n"
            "/help       — Esta mensagem\n\n"
            "<b>💬 GROK - Interação livre</b>\n"
            "<i>Mande qualquer pergunta em texto livre — "
            "o Grok vai analisar o bot e responder!</i>\n\n"
            "Exemplos:\n"
            "• Como está o bot?\n"
            "• Qual o win rate?\n"
            "• Vale abrir novo trade agora?"
        )

    else:
        # Qualquer texto que não seja comando → Grok analisa
        print(f"[Grok] Processando: {texto[:50]}...")
        resposta = _perguntar_grok(texto)
        enviar_mensagem(resposta)


# ──────────────────────────────────────────────────────────────
# LISTENER LONG-POLLING
# ──────────────────────────────────────────────────────────────

def iniciar_listener():
    """Inicia listener de mensagens Telegram em thread daemon."""
    def listen():
        offset = 0
        print("Listener Telegram iniciado...")
        while True:
            try:
                r = requests.get(
                    f"{TELEGRAM_API}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                    timeout=35,
                )
                if r.status_code == 200:
                    dados = r.json()
                    if dados.get("ok") and dados.get("result"):
                        for update in dados["result"]:
                            offset = update["update_id"] + 1
                            msg    = update.get("message", {})
                            texto  = msg.get("text", "").strip()
                            if texto:
                                print(f"Telegram: {texto[:60]}")
                                processar_comando(texto)
                time.sleep(1)
            except Exception as e:
                print(f"Listener erro: {e}")
                time.sleep(5)

    Thread(target=listen, daemon=True).start()


if __name__ == "__main__":
    print("Testando Telegram...")
    ok = enviar_mensagem("Notificador OK!")
    print("OK" if ok else "Falhou")
