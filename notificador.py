"""
NOTIFICADOR TELEGRAM — WEATHER QUANT
Notificações com matemática Kelly completa + tabela de validação.
"""

import os, requests, json, subprocess, time
from datetime import datetime
from threading import Thread
from config import TELEGRAM_TOKEN, CHAT_ID, MAX_POSITION, KELLY_FRACTION

BOT_DIR      = os.path.dirname(os.path.abspath(__file__))
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ──────────────────────────────────────────────────────────────
# BASE
# ──────────────────────────────────────────────────────────────

def enviar_mensagem(texto, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️  Telegram: TELEGRAM_TOKEN ou CHAT_ID não configurados no .env")
        return False
    try:
        r = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": CHAT_ID, "text": texto, "parse_mode": parse_mode},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"⚠️  Telegram HTTP {r.status_code}: {r.text[:200]}")
            return False
        return True
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

    icone_t = ("✅ EXATO" if acertou else ("✅ CORRETO" if resultado=="WIN" else "❌ ERRADO"))
    icone_p = "✅ CORRETO" if resultado=="WIN" else "❌ ERRADO"
    brier   = round((model_prob - (1.0 if resultado=="WIN" else 0.0))**2, 4)
    b_label = "Excelente" if brier < 0.1 else ("Bom" if brier < 0.25 else "Ruim")

    return (
        f"\n\n<b>🧪 Validacao Realizada</b>\n"
        f"<pre>"
        f"Parametro    | Previsao | Real\n"
        f"-------------|----------|-------------------\n"
        f"Temperatura  | {tgt_str:<8} | {real_str}\n"
        f"             | {icone_t}\n"
        f"Probabilid.  | {model_prob*100:.0f}%      | {icone_p}\n"
        f"Brier Score  | --       | {brier} ({b_label})"
        f"</pre>"
    )

# ──────────────────────────────────────────────────────────────
# NOTIFICAÇÕES DE TRADE
# ──────────────────────────────────────────────────────────────

def notificar_entrada_trade(city, market_date, target, unit, stake,
                             model_prob, market_price, edge,
                             balance=None, shares=None):
    ev_pct     = round((model_prob / market_price - 1) * 100, 1) if market_price > 0 else 0
    shares_ln  = f"\n<b>Shares:</b> {shares}" if shares is not None else ""

    kelly_block = ""
    if balance is not None and balance > 0:
        km = _kelly_math(balance, model_prob, market_price)
        kelly_block = (
            f"\n\n<b>A matematica completa</b>\n"
            f"{city} — o Kelly puro diz apostar <b>{km['kelly_puro_pct']}%</b> do bankroll. "
            f"O half-Kelly diz <b>{km['half_kelly_pct']}%</b>. "
            f"Voce capeou em <b>{km['cap_pct']}%</b> — correto.\n"
        )
        if km["desperdicio_pct"] > 5:
            kelly_block += (
                f"O arredondamento de shares consumiu "
                f"<b>{km['desperdicio_pct']}%</b> do stake calculado "
                f"(teorico ${km['stake_teorico']:.2f} → real ${km['custo_real']:.2f})."
            )
        else:
            kelly_block += (
                f"Granularidade OK — teorico ${km['stake_teorico']:.2f} "
                f"→ real ${km['custo_real']:.2f} ({km['desperdicio_pct']}% perdido)."
            )

    msg = (
        f"<b>NOVO TRADE</b>\n\n"
        f"<b>Cidade:</b> {city}\n"
        f"<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> <b>${stake:.2f}</b>{shares_ln}\n\n"
        f"<b>Probabilidades</b>\n"
        f"Modelo:   <b>{model_prob*100:.1f}%</b>\n"
        f"Mercado:  <b>{market_price*100:.1f}%</b>\n"
        f"Edge:     <b>+{edge:.1f}%</b>\n"
        f"EV:       <b>+{ev_pct:.1f}%</b>"
        f"{kelly_block}\n\n"
        f"Aguardando resolucao..."
    )
    enviar_mensagem(msg)


def notificar_settlement_win(city, market_date, target, unit, stake, pnl, saldo,
                              model_prob=None, real_temp_c=None):
    tabela = _tabela_validacao(target, unit, model_prob, real_temp_c, "WIN")
    enviar_mensagem(
        f"<b>VITORIA!</b>\n\n"
        f"<b>Cidade:</b> {city}\n<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> ${stake:.2f}\n"
        f"<b>Ganho:</b> <b>+${pnl:.2f}</b>"
        f"{tabela}\n\n"
        f"Saldo: <b>${saldo:.2f}</b>"
    )


def notificar_settlement_loss(city, market_date, target, unit, stake, pnl, saldo,
                               model_prob=None, real_temp_c=None):
    tabela = _tabela_validacao(target, unit, model_prob, real_temp_c, "LOSS")
    enviar_mensagem(
        f"<b>DERROTA</b>\n\n"
        f"<b>Cidade:</b> {city}\n<b>Data:</b> {market_date}\n"
        f"<b>Target:</b> {target}°{unit}\n"
        f"<b>Aposta:</b> ${stake:.2f}\n"
        f"<b>Perda:</b> <b>-${abs(pnl):.2f}</b>"
        f"{tabela}\n\n"
        f"Saldo: <b>${saldo:.2f}</b>"
    )


def notificar_settlement_resumo(total_resolved, wins, losses, total_pnl, saldo):
    taxa  = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0.0
    emoji = "🟢" if total_pnl >= 0 else "🔴"
    enviar_mensagem(
        f"<b>SETTLEMENT CONCLUIDO</b>\n\n"
        f"<b>Resolvidos:</b> {total_resolved}\n"
        f"{wins} vitorias | {losses} derrotas\n"
        f"<b>Win rate:</b> {taxa:.1f}%\n\n"
        f"{emoji} <b>PnL sessao:</b> ${total_pnl:+.2f}\n"
        f"Saldo atual: <b>${saldo:.2f}</b>"
    )

# ──────────────────────────────────────────────────────────────
# LISTENER DE COMANDOS
# ──────────────────────────────────────────────────────────────

def processar_comando(comando):
    cmd = comando.lower().strip()

    if cmd == "/settlement":
        enviar_mensagem("Executando settlement...")
        try:
            res = subprocess.run(
                ["python", "settlement.py"],
                capture_output=True, text=True, timeout=60, cwd=BOT_DIR,
            )
            if res.returncode == 0:
                enviar_mensagem("Settlement executado com sucesso!")
            else:
                erro = res.stderr[:500] if res.stderr else "sem detalhes"
                enviar_mensagem(f"Erro no settlement:\n<pre>{erro}</pre>")
        except subprocess.TimeoutExpired:
            enviar_mensagem("Timeout: settlement demorou mais de 60s")
        except Exception as e:
            enviar_mensagem(f"Erro ao executar settlement: {e}")

    elif cmd == "/status":
        try:
            with open(os.path.join(BOT_DIR, "bankroll.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
            saldo     = data.get("balance", 0)
            history   = data.get("history", [])
            abertos   = [t for t in history if t.get("result") == "OPEN"]
            fechados  = [t for t in history if t.get("result") in ("WIN", "LOSS")]
            wins_lst  = [t for t in history if t.get("result") == "WIN"]
            taxa      = (len(wins_lst) / len(fechados) * 100) if fechados else 0
            pnl_total = sum(t.get("pnl", 0) for t in fechados)
            exposicao = sum(t.get("stake", 0) for t in abertos)
            emoji     = "🟢" if pnl_total >= 0 else "🔴"
            det = "".join(
                f"\n  • {t.get('city','?')} {t.get('market_date','?')} "
                f"${t.get('stake',0):.2f} @ {t.get('model_prob',0)*100:.0f}%"
                for t in abertos[:5]
            )
            enviar_mensagem(
                f"<b>STATUS DO BOT</b>\n\n"
                f"Saldo: <b>${saldo:.2f}</b>\n"
                f"Exposicao: ${exposicao:.2f}\n"
                f"Trades abertos: {len(abertos)}{det}\n"
                f"Fechados: {len(fechados)} ({len(wins_lst)}W / {len(fechados)-len(wins_lst)}L)\n"
                f"Win rate: {taxa:.1f}%\n"
                f"{emoji} PnL total: <b>${pnl_total:+.2f}</b>"
            )
        except FileNotFoundError:
            enviar_mensagem("bankroll.json nao encontrado")
        except Exception as e:
            enviar_mensagem(f"Erro ao ler status: {e}")

    elif cmd == "/validacao":
        try:
            from validacao import gerar_relatorio
            gerar_relatorio(enviar_telegram=True)
        except Exception as e:
            enviar_mensagem(f"Erro ao gerar validacao: {e}")

    elif cmd == "/help":
        enviar_mensagem(
            "<b>COMANDOS DISPONIVEIS</b>\n\n"
            "<b>/settlement</b> — Rodar settlement manualmente\n"
            "<b>/status</b>     — Ver saldo, exposicao e trades abertos\n"
            "<b>/validacao</b>  — Relatorio de validacao do modelo\n"
            "<b>/help</b>       — Esta mensagem"
        )
    else:
        enviar_mensagem(f"Comando desconhecido: <code>{comando}</code>\nUse /help.")


def iniciar_listener():
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
                            texto  = update.get("message", {}).get("text", "")
                            if texto.startswith("/"):
                                print(f"Comando: {texto}")
                                processar_comando(texto)
                time.sleep(1)
            except Exception as e:
                print(f"Listener erro: {e}")
                time.sleep(5)

    Thread(target=listen, daemon=True).start()


if __name__ == "__main__":
    print("Testando Telegram...")
    ok = enviar_mensagem("Notificador OK! Bot conectado.")
    print("OK" if ok else "Falhou — verifique .env")
