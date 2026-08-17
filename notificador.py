"""
NOTIFICADOR TELEGRAM — WEATHER QUANT
Notificações automáticas + IA Groq (llama-3.3-70b) para conversa natural.

CORRIGIDO: docstring dizia "Grok" (xAI), mas o serviço usado é Groq
(startup de infraestrutura, groq.com). São produtos diferentes.
Variável de ambiente: GROQ_API_KEY (correta).

CORREÇÕES (auditoria):
1. AUTENTICAÇÃO: o listener agora SÓ processa mensagens vindas do
   CHAT_ID configurado. Antes, QUALQUER pessoa que encontrasse o bot no
   Telegram podia executar /resetbankroll (zerando histórico e saldo) e
   /settlement — o bot processava comandos de qualquer chat e apenas
   respondia no CHAT_ID.
2. /settlement agora roda EM PROCESSO via settle_all(), que é atômico
   (advisory lock + lock de arquivo). Antes era um SUBPROCESSO
   `python settlement.py` rodando em paralelo com o loop principal do
   worker — terceiro escritor concorrente do bankroll sem lock, um dos
   vetores da divergência de saldo.
3. Brier do contexto da IA agora é ciente do lado (NO → 1−model_prob),
   consistente com validacao.py.

PATCH (correção aplicada nesta versão):
4. iniciar_listener(): a chamada a _chat_autorizado(msg) estava
   COMENTADA ("Temporariamente desativando trava de segurança para
   diagnóstico"), desfazendo a correção do item 1 acima. Com isso,
   QUALQUER pessoa que encontrasse o bot no Telegram podia de novo
   executar /resetbankroll e /settlement. Reativada.
"""

import os
import requests
import json
import time
import logging
from datetime import datetime, timezone
from threading import Thread

logger = logging.getLogger(__name__)

from config import (
    TELEGRAM_TOKEN,
    CHAT_ID,
    MAX_POSITION,
    KELLY_FRACTION,
    MAX_KELLY_FRACTION_CAP,
)

BOT_DIR      = os.path.dirname(os.path.abspath(__file__))
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ──────────────────────────────────────────────────────────────
# ENVIO BASE
# ──────────────────────────────────────────────────────────────

def enviar_mensagem(texto, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("Telegram: token ou chat_id não configurados")
        return False
    try:
        r = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": CHAT_ID, "text": texto, "parse_mode": parse_mode},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        logger.error("Telegram erro: %s", e)
        return False


# ──────────────────────────────────────────────────────────────
# KELLY MATH HELPER
# ──────────────────────────────────────────────────────────────

def _kelly_math(balance, model_prob, market_price):
    # Odds líquidas com fee — consistente com risk.kelly_criterion.
    try:
        from risk import FEE_RATE
    except Exception:
        FEE_RATE = 0.02
    p, q = model_prob, 1.0 - model_prob
    b    = ((1.0 - FEE_RATE) / market_price) - 1.0 if market_price > 0 else 0
    f_puro  = max((p * b - q) / b, 0.0) if b > 0 else 0.0
    f_half  = f_puro * KELLY_FRACTION
    f_cap   = min(f_half, MAX_KELLY_FRACTION_CAP)
    stake_t = round(balance * f_cap, 2)
    stake_t = min(stake_t, MAX_POSITION)
    shares  = int(stake_t / market_price) if market_price > 0 else 0
    custo   = round(shares * market_price, 2)
    desp    = round((1 - custo / stake_t) * 100, 1) if stake_t > 0 else 0
    ev_pct  = round((p * (1.0 - FEE_RATE) / market_price - 1) * 100, 1) if market_price > 0 else 0
    return {
        "kelly_puro_pct": round(f_puro * 100, 1),
        "half_kelly_pct": round(f_half * 100, 1),
        "cap_pct":        int(round(MAX_KELLY_FRACTION_CAP * 100, 0)),
        "cap_usd":        MAX_POSITION,
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

def notificar_quase_trade(city, market_date, target, unit, model_prob, market_price, edge, min_edge, reason):
    """Notifica quando um trade foi bloqueado por pouco (v5.7)."""
    enviar_mensagem(
        f"<b>⚠️ QUASE-TRADE (BLOQUEADO)</b>\n\n"
        f"<b>Cidade:</b> {city}\n"
        f"<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Motivo:</b> {reason}\n\n"
        f"Modelo: <b>{model_prob*100:.1f}%</b> | "
        f"Mercado: <b>{market_price*100:.1f}%</b>\n"
        f"Edge: <b>{edge*100:+.1f}%</b> (Min: {min_edge*100:.1f}%)"
    )


def notificar_entrada_trade(city, market_date, target, unit, stake,
                             model_prob, market_price, edge,
                             balance=None, shares=None):
    ev_pct    = round((model_prob / market_price - 1) * 100, 1) if market_price > 0 else 0
    shares_ln = f"\n<b>Shares:</b> {shares}" if shares is not None else ""

    kelly_block = ""
    if balance is not None and balance > 0:
        km = _kelly_math(balance, model_prob, market_price)
        kelly_block = (
            f"\n\n<b>Matematica Kelly</b>\n"
            f"Kelly puro: <b>{km['kelly_puro_pct']}%</b> | "
            f"Half-Kelly: <b>{km['half_kelly_pct']}%</b> | "
            f"Cap: <b>{km['cap_pct']}%</b> / ${km['cap_usd']:.2f}\n"
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
        f"Edge: <b>+{edge*100:.1f}%</b> | EV: <b>+{ev_pct:.1f}%</b>"
        f"{kelly_block}\n\n"
        f"Aguardando resolucao..."
    )


def notificar_settlement_win(city, market_date, target, unit, stake, pnl, saldo,
                              model_prob=None, real_temp_c=None):
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
    tabela = _tabela_validacao(target, unit, model_prob, real_temp_c, "LOSS")
    enviar_mensagem(
        f"<b>DERROTA</b>\n\n"
        f"<b>Cidade:</b> {city} | <b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> ${stake:.2f} | <b>Perda: -${abs(pnl):.2f}</b>"
        f"{tabela}\n\nSaldo: <b>${saldo:.2f}</b>"
    )


def notificar_settlement_resumo(total_resolved, wins, losses, total_pnl, saldo):
    taxa  = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0.0
    emoji = "🟢" if total_pnl >= 0 else "🔴"
    enviar_mensagem(
        f"<b>SETTLEMENT CONCLUIDO</b>\n\n"
        f"Resolvidos: {total_resolved} | "
        f"{wins}W / {losses}L | WR: {taxa:.1f}%\n\n"
        f"{emoji} PnL: <b>${total_pnl:+.2f}</b> | Saldo: <b>${saldo:.2f}</b>"
    )


# ──────────────────────────────────────────────────────────────
# IA — GROQ (llama-3.3-70b) COMO ANALISTA DO BOT
#
# CORRIGIDO: docstring e variável interna renomeados de "grok"
# para "groq" — são serviços diferentes:
#   xAI Grok   → api.x.ai  (produto da xAI/Elon Musk)
#   Groq        → api.groq.com (startup de infra de IA)
# O bot usa GROQ, não Grok.
# ──────────────────────────────────────────────────────────────

def _build_context():
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
            f"Model {t.get('model_prob',0)*100:.0f}% vs Mkt {t.get('market_price',0)*100:.0f}%"
        )

    validacao_str = ""
    if fechados and any(t.get("model_prob") for t in fechados):
        def _prob_lado(t):
            p = t.get("model_prob", 0) or 0
            return (1.0 - p) if str(t.get("side", "YES")).upper() == "NO" else p
        brier_scores = [
            (_prob_lado(t) - (1.0 if t.get("result") == "WIN" else 0))**2
            for t in fechados if t.get("model_prob")
        ]
        if brier_scores:
            brier_mean = round(sum(brier_scores) / len(brier_scores), 4)
            validacao_str = f"\n- Brier Score médio: {brier_mean}"

    # Carrega parâmetros reais do config (não hardcoded)
    try:
        from config import (
            MIN_PROB_ABOVE_BELOW, MIN_PRICE, MIN_TARGET_ZSCORE,
            MAX_POSITION, MAX_TOTAL_EXPOSURE, MAX_OPEN_TRADES,
            START_BALANCE,
        )
    except Exception:
        MIN_PROB_ABOVE_BELOW = 0.72
        MIN_PRICE = 0.15
        MIN_TARGET_ZSCORE = 1.0
        MAX_POSITION = 4.0
        MAX_TOTAL_EXPOSURE = 20.0
        MAX_OPEN_TRADES = 5
        START_BALANCE = 100.0

    return f"""CONTEXTO DO BOT DE APOSTA — WEATHER QUANTITATIVO:

SITUACAO ATUAL:
- Saldo: ${balance:.2f}
- PnL total: ${pnl:+.2f}
- Win rate: {win_rate}% ({len(wins)}W/{len(fechados)-len(wins)}L)
- Trades abertos: {len(abertos)} (exposição ${exposicao:.2f})
- Total fechados: {len(fechados)}{validacao_str}

TRADES ABERTOS:{abertos_str if abertos_str else ' Nenhum'}

ÚLTIMOS TRADES FECHADOS:{trades_str if trades_str else ' Nenhum'}

SOBRE O BOT (Weather Quant v5.1):
- Usa Open-Meteo para forecast de temperatura máxima diária (22 cidades)
- Modelo Normal com sigma calibrado: D+1=4.0°C, D+2=4.5°C, D+3=5.0°C
- Filtros ativos: prob >= {MIN_PROB_ABOVE_BELOW*100:.0f}%, zscore >= {MIN_TARGET_ZSCORE:.1f}, market_price >= {MIN_PRICE:.2f}
- Kelly dinâmico: 50% base → 35% após 2 perdas → 25% após 3+ perdas
- Cooldown: 3 losses = 4h, 5 losses = 12h (settlement continua)
- Cap ${MAX_POSITION:.0f} por trade, exposição máxima ${MAX_TOTAL_EXPOSURE:.0f}, máximo {MAX_OPEN_TRADES} abertos
- Beijing e Hong Kong bloqueados (erro histórico > 5°C)
- Confirmação intra-dia para mercados D+0/D+1
- Settlement automático via scheduler horário
- Saldo inicial: ${START_BALANCE:.0f}

Responda de forma concisa em português. Máximo 3 parágrafos."""


def _perguntar_groq(pergunta_usuario):
    """
    Envia pergunta para Groq (api.groq.com), não xAI Grok.
    Usa llama-3.3-70b-versatile.
    Variável de ambiente: GROQ_API_KEY
    """
    contexto = _build_context()

    # CORRIGIDO: era "grok_key" — nome consistente com a variável de ambiente
    groq_api_key = os.environ.get("GROQ_API_KEY", "")

    if not groq_api_key:
        return "GROQ_API_KEY não configurada.\n\nAdicione a variável de ambiente com sua chave Groq (groq.com)."

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_api_key}",
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
            timeout=30,
        )

        if r.status_code == 200:
            data = r.json()
            return data["choices"][0]["message"]["content"]
        else:
            data = r.json() if r.text else {}
            erro = data.get("error", {}).get("message", "erro desconhecido") if isinstance(data, dict) else str(data)
            return f"Erro Groq {r.status_code}: {erro}"

    except requests.exceptions.Timeout:
        return "Timeout — Groq demorou muito. Tente novamente."
    except requests.exceptions.ConnectionError as e:
        return f"Falha de conexão com Groq: {str(e)[:100]}"
    except Exception as e:
        return f"Erro ao conectar com Groq: {str(e)[:200]}"


# Aliases para compatibilidade com código existente
_perguntar_ia     = _perguntar_groq
_perguntar_claude = _perguntar_groq
_perguntar_grok   = _perguntar_groq  # alias para código antigo que ainda usa esse nome


# ──────────────────────────────────────────────────────────────
# COMANDOS DO TELEGRAM
# ──────────────────────────────────────────────────────────────

def processar_comando(texto):
    cmd = texto.lower().strip()

    if cmd == "/settlement":
        enviar_mensagem("Executando settlement...")
        try:
            # Em processo, sob o mesmo lock do bankroll — NÃO mais via
            # subprocesso paralelo (que escrevia o bankroll por fora do
            # processo principal, sem coordenação).
            from settlement import settle_all
            settle_all()
            enviar_mensagem("Settlement executado!")
        except Exception as e:
            enviar_mensagem(f"Erro no settlement:\n<pre>{str(e)[:400]}</pre>")

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

    elif cmd == "/health":
        try:
            from dashboard import load_data
            from operational_health import build_operational_health

            data, warning = load_data()
            health = build_operational_health(data or {}, warning)
            counts = health.get("decision_counts", {})
            enviar_mensagem(
                "<b>HEALTH OPERACIONAL</b>\n\n"
                f"Status: <b>{health.get('status')}</b>\n"
                f"Resumo: {health.get('summary')}\n"
                f"Bot ativo: {health.get('bot_active')}\n"
                f"DB ok: {health.get('db_ok')} ({health.get('data_source')})\n"
                f"Ultima decisao: {health.get('last_decision_ts')}\n"
                f"Idade decisao: {health.get('last_decision_age_seconds')}s\n"
                f"Motivo dominante: {health.get('dominant_block_reason')}\n\n"
                f"Decisoes recentes: {counts.get('total', 0)} | "
                f"bloqueadas {counts.get('blocked', 0)} | "
                f"trades {counts.get('recorded', 0)} | "
                f"sinais {counts.get('signal', 0)} | "
                f"erros {counts.get('error', 0)}"
            )
        except Exception as e:
            enviar_mensagem(f"Erro ao ler health: {e}")

    elif cmd.startswith("/resetbankroll"):
        # AUDITORIA bug #29: antes executava imediato — um botão mal
        # clicado no Telegram removia TODO o histórico. Agora exige
        # confirmação explícita em 2 passos:
        #   1) /resetbankroll [valor]     -> pede confirmação
        #   2) /resetbankroll CONFIRMAR [valor]  -> executa
        parts = cmd.split()
        confirm_token = parts[1] if len(parts) > 1 else ""
        if confirm_token != "confirmar":
            try:
                valor = float(parts[1]) if len(parts) > 1 else 200.0
            except Exception:
                valor = 200.0
            enviar_mensagem(
                f"<b>CONFIRMAÇÃO NECESSÁRIA</b>\n\n"
                f"Estás prestes a resetar o bankroll para <b>${valor:.2f}</b>, "
                f"apagando TODO o histórico de trades.\n\n"
                f"Isto é irreversível.\n\n"
                f"Para confirmar, envia:\n"
                f"<code>/resetbankroll confirmar {valor:g}</code>"
            )
            return
        # Segundo passo: CONFIRMAR presente
        try:
            valor = float(parts[2]) if len(parts) > 2 else 200.0
            valor = max(10.0, min(valor, 10000.0))
        except Exception:
            valor = 200.0
        try:
            from bankroll import reset_bankroll
            reset_bankroll(valor)
            enviar_mensagem(
                f"<b>BANKROLL RESETADO</b>\n\n"
                f"Novo saldo: <b>${valor:.2f}</b>\n"
                f"Histórico zerado.\n\n"
                f"Bot vai começar com dados limpos no próximo ciclo."
            )
        except Exception as e:
            enviar_mensagem(f"Erro ao resetar: {e}")

    elif cmd == "/help":
        enviar_mensagem(
            "<b>⚡ WEATHER QUANT BOT — COMANDOS</b>\n\n"
            "/status                  — Saldo e trades abertos\n"
            "/health                  — Saúde operacional do loop\n"
            "/validacao               — Relatório do modelo\n"
            "/settlement              — Liquidar agora\n"
            "/resetbankroll [valor]   — Resetar saldo (exige CONFIRMAR)\n"
            "/help                    — Esta mensagem\n\n"
            "<b>💬 Conversa livre com IA</b>\n"
            "<i>Manda qualquer pergunta — a IA (Groq llama-3.3-70b) "
            "analisa o bot em tempo real e responde.</i>\n\n"
            "Exemplos:\n"
            "• Como está o desempenho?\n"
            "• Quais trades estão abertos?\n"
            "• O modelo está calibrado?\n"
            "• Vale a pena continuar apostando?"
        )

    else:
        logger.info("[Groq] Processando: %s", texto[:50])
        resposta = _perguntar_groq(texto)
        enviar_mensagem(resposta)


# ──────────────────────────────────────────────────────────────
# LISTENER LONG-POLLING
# ──────────────────────────────────────────────────────────────

def _chat_autorizado(msg: dict) -> bool:
    """
    Só o CHAT_ID configurado pode comandar o bot. Sem isto, qualquer
    pessoa que encontre o bot no Telegram pode resetar o bankroll ou
    disparar settlement.
    """
    try:
        chat_id = str(msg.get("chat", {}).get("id", ""))
        return bool(CHAT_ID) and chat_id == str(CHAT_ID)
    except Exception:
        return False


def iniciar_listener():
    def listen():
        # Resetando offset para pegar apenas mensagens NOVAS (v5.7.1)
        offset = -1 
        logger.info("Listener Telegram iniciado...")
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
                            if not texto:
                                continue
                            # PATCH: trava de segurança reativada — estava
                            # comentada ("diagnóstico"), o que permitia
                            # qualquer chat executar comandos sensíveis
                            # (/resetbankroll, /settlement).
                            if not _chat_autorizado(msg):
                                quem = msg.get("chat", {}).get("id", "?")
                                logger.warning(
                                    "Telegram: mensagem de chat NÃO autorizado (%s) — ignorada. CHAT_ID configurado: %s",
                                    quem, CHAT_ID,
                                )
                                continue
                            logger.info("Telegram: %s", texto[:60])
                            processar_comando(texto)
                time.sleep(1)
            except Exception as e:
                logger.error("Listener erro: %s", e)
                time.sleep(5)

    Thread(target=listen, daemon=True).start()


if __name__ == "__main__":
    print("Testando Telegram...")
    ok = enviar_mensagem("Notificador OK!")
    print("OK" if ok else "Falhou")
