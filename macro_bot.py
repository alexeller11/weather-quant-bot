"""
macro_bot.py — Módulo de trading em mercados macroeconômicos.

CORRIGIDO:
- `import re` e `import json` estavam no meio do arquivo, depois de funções
  que já os usavam. Isso causava NameError em runtime para qualquer chamada
  a _handle_nfp_window() ou ao bloco de observação do loop principal.
  Ambos movidos para o topo junto com os demais imports.

Roda como thread daemon dentro do bot.py existente.
Compartilha bankroll, risk, notificador com o módulo de temperatura.

Estratégia:
  1. Monitora calendário de eventos (CPI, NFP, FOMC, GDP)
  2. Quando entra na janela de publicação, busca mercados ativos
  3. Após dado publicado, lê valor real via BLS/FRED
  4. Calcula qual bucket da Polymarket o dado resolve
  5. Aposta YES nos buckets corretos / NO nos incorretos
  6. Janela típica: 30s a 5 minutos após publicação
"""

import os
import re
import json
import time
import traceback
from datetime import datetime, timezone
from threading import Thread

from bankroll import load_bankroll, save_bankroll, already_traded
from notificador import enviar_mensagem

from config import (
    MAX_TOTAL_EXPOSURE,
    MAX_OPEN_TRADES,
    MAX_POSITION,
    KELLY_FRACTION,
    TRADING_ENABLED,
)

from macro_calendar import (
    get_active_windows,
    get_upcoming_events,
    MACRO_EVENTS,
)
from macro_data import (
    get_cpi_latest,
    get_nfp_latest,
    get_fomc_rate,
    identify_cpi_bucket,
)
from macro_parser import (
    fetch_macro_markets,
    find_edge_cpi,
    find_edge_fomc,
)

# =========================================================
# CONFIG MACRO
# =========================================================

MACRO_TRADING_ENABLED = os.getenv("MACRO_TRADING_ENABLED", "0") == "1"
MACRO_MIN_EDGE        = float(os.getenv("MACRO_MIN_EDGE", "0.20"))
MACRO_MAX_POSITION    = float(os.getenv("MACRO_MAX_POSITION", "2.00"))
MACRO_POLL_INTERVAL   = 30
MACRO_IDLE_INTERVAL   = 300


# =========================================================
# UTILS
# =========================================================

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _log(msg):
    ts = utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[macro] {ts} | {msg}")


def _kelly_stake(balance, prob, price):
    """Half-Kelly simplificado para macros."""
    if prob <= 0 or prob >= 1 or price <= 0:
        return 0.0
    b = (1.0 / price) - 1.0
    q = 1.0 - prob
    f = max((prob * b - q) / b, 0.0) if b > 0 else 0.0
    return round(balance * f * KELLY_FRACTION, 2)


def _expected_value(prob, price):
    if price <= 0:
        return 0.0
    return round(prob / price - 1.0, 4)


def _open_exposure(history):
    return sum(float(t.get("stake", 0)) for t in history if t.get("result") == "OPEN")


def _remaining_capacity(history):
    return max(0.0, MAX_TOTAL_EXPOSURE - _open_exposure(history))


# =========================================================
# LEITURA DE DADO REAL
# =========================================================

def _get_real_data(event_type):
    try:
        if event_type == "CPI":
            return get_cpi_latest()
        elif event_type == "NFP":
            return get_nfp_latest()
        elif event_type == "FOMC":
            return get_fomc_rate()
        else:
            _log(f"Tipo não suportado: {event_type}")
            return None
    except Exception as e:
        _log(f"Erro ao ler dado real ({event_type}): {e}")
        return None


# =========================================================
# PROCESSAMENTO DE OPORTUNIDADES
# =========================================================

def _process_opportunities(opportunities, bankroll, session_tag):
    if not opportunities:
        return 0

    history  = bankroll.get("history", [])
    balance  = float(bankroll.get("balance", 0))
    opened   = 0

    for opp in opportunities:
        open_count = len([t for t in history if t.get("result") == "OPEN"])
        if open_count >= MAX_OPEN_TRADES:
            _log("Limite de trades abertos atingido")
            break

        remaining = _remaining_capacity(history)
        if remaining <= 0:
            _log("Exposição máxima atingida")
            break

        market_id   = opp["market_id"]
        question    = opp["question"]
        edge        = opp["edge"]
        model_prob  = opp["model_prob"]
        trade_side  = opp["trade_side"]
        trade_price = opp["trade_price"]
        event_type  = opp["event_type"]

        if already_traded(history, market_id):
            _log(f"Já tem posição em: {market_id}")
            continue

        if abs(edge) < MACRO_MIN_EDGE:
            _log(f"Edge insuficiente: {edge:.3f}")
            continue

        if trade_price < 0.10 or trade_price > 0.92:
            _log(f"Preço fora do range: {trade_price:.3f}")
            continue

        ev = _expected_value(model_prob, trade_price)
        if ev <= 0:
            _log(f"EV negativo: {ev:.4f}")
            continue

        stake  = _kelly_stake(balance, model_prob, trade_price)
        stake  = min(stake, remaining, MACRO_MAX_POSITION, MAX_POSITION)
        shares = int(stake / trade_price) if trade_price > 0 else 0
        if shares <= 0:
            continue

        real_cost = round(shares * trade_price, 2)
        stake     = real_cost
        if stake <= 0:
            continue

        _log(
            f"TRADE [{event_type}] {trade_side} | "
            f"market={market_id} | edge={edge:+.3f} | "
            f"prob={model_prob:.2f} | stake=${stake:.2f}"
        )

        trade = {
            "id":           f"macro_{market_id}_{int(time.time())}",
            "market_id":    market_id,
            "city":         f"[MACRO] {event_type}",
            "question":     question[:120],
            "market_date":  opp.get("release_date", utcnow().date().isoformat()),
            "entry_time":   utcnow().isoformat(),
            "exit_time":    None,
            "type":         f"MACRO_{trade_side}",
            "target":       0,
            "forecast_c":   0,
            "sigma_total":  0,
            "shares":       shares,
            "model_prob":   round(model_prob, 4),
            "market_price": round(trade_price, 4),
            "edge":         round(edge, 4),
            "ev":           round(ev, 4),
            "stake":        stake,
            "result":       "OPEN",
            "pnl":          0,
            "unit":         "USD",
            "forecast_day": 0,
            "macro_event":  event_type,
            "macro_side":   trade_side,
            "session":      session_tag,
        }

        history.append(trade)
        balance -= stake
        opened  += 1

        try:
            enviar_mensagem(
                f"<b>MACRO TRADE [{event_type}]</b>\n\n"
                f"<b>Side:</b> {trade_side}\n"
                f"<b>Pergunta:</b> {question[:80]}\n"
                f"<b>Aposta:</b> <b>${stake:.2f}</b> ({shares} shares)\n\n"
                f"Modelo: <b>{model_prob*100:.0f}%</b> | "
                f"Mercado: <b>{trade_price*100:.0f}%</b>\n"
                f"Edge: <b>{edge*100:+.1f}%</b> | EV: <b>{ev*100:+.1f}%</b>"
            )
        except Exception as e:
            _log(f"Telegram erro: {e}")

    bankroll["balance"] = balance
    return opened


# =========================================================
# HANDLERS POR EVENTO
# =========================================================

def _handle_cpi_window(bankroll, secs_since_release):
    _log(f"Janela CPI ativa ({secs_since_release:.0f}s após publicação)")
    if secs_since_release < 90:
        _log("Aguardando BLS API atualizar (< 90s)...")
        return 0

    cpi_data = get_cpi_latest()
    if not cpi_data:
        _log("CPI: dado indisponível via BLS API")
        return 0

    _log(f"CPI: YoY={cpi_data['yoy']:+.1f}% | MoM={cpi_data['mom']:+.1f}%")
    markets = fetch_macro_markets(event_types=["CPI"])
    opps    = find_edge_cpi(markets, cpi_data)
    if not opps:
        _log("CPI: nenhuma oportunidade com edge suficiente")
        return 0

    _log(f"CPI: {len(opps)} oportunidades encontradas")
    session_tag = f"CPI_{cpi_data['month']}_{cpi_data['year']}"
    return _process_opportunities(opps, bankroll, session_tag)


def _handle_fomc_window(bankroll, secs_since_release):
    _log(f"Janela FOMC ativa ({secs_since_release:.0f}s após publicação)")
    if secs_since_release < 30:
        _log("Aguardando FRED API atualizar (< 30s)...")
        return 0

    fomc_data = get_fomc_rate()
    if not fomc_data:
        _log("FOMC: dado indisponível")
        return 0

    rate = fomc_data["rate"]
    _log(f"FOMC: rate={rate}%")

    if rate <= 3.25:
        decision = "cut_25"
    elif rate <= 3.75:
        decision = "hold"
    elif rate >= 4.00:
        decision = "hike_25"
    else:
        decision = "hold"

    _log(f"FOMC: decisão inferida = {decision}")
    markets = fetch_macro_markets(event_types=["FOMC"])
    opps    = find_edge_fomc(markets, rate, decision)
    if not opps:
        _log("FOMC: nenhuma oportunidade")
        return 0

    session_tag = f"FOMC_{fomc_data['date']}"
    return _process_opportunities(opps, bankroll, session_tag)


def _handle_nfp_window(bankroll, secs_since_release):
    _log(f"Janela NFP ativa ({secs_since_release:.0f}s após publicação)")
    if secs_since_release < 90:
        _log("Aguardando BLS API atualizar (< 90s)...")
        return 0

    nfp_data = get_nfp_latest()
    if not nfp_data:
        _log("NFP: dado indisponível")
        return 0

    _log(
        f"NFP: {nfp_data['nfp']:+.0f}k | "
        f"Desemprego: {nfp_data['unemployment']}%"
    )

    markets = fetch_macro_markets(event_types=["NFP"])
    nfp_val = nfp_data["nfp"]
    opps    = []

    for mkt in markets:
        if mkt["event_type"] != "NFP":
            continue

        q         = mkt["question"].lower()
        yes_price = mkt["yes_price"]
        resolves_yes = None

        match_above = re.search(r"(?:above|more than|over)\s+(\d+)k", q)
        match_below = re.search(r"(?:below|less than|under)\s+(\d+)k", q)

        if match_above:
            threshold    = int(match_above.group(1))
            resolves_yes = nfp_val > threshold
        elif match_below:
            threshold    = int(match_below.group(1))
            resolves_yes = nfp_val < threshold

        if "unemployment" in q:
            match_rate = re.search(r"(\d+\.\d+)\s*%", q)
            if match_rate and nfp_data.get("unemployment"):
                unemp_threshold = float(match_rate.group(1))
                if "above" in q or "higher" in q:
                    resolves_yes = nfp_data["unemployment"] > unemp_threshold
                elif "below" in q or "lower" in q:
                    resolves_yes = nfp_data["unemployment"] < unemp_threshold

        if resolves_yes is None:
            continue

        model_prob = 0.95 if resolves_yes else 0.05
        edge       = model_prob - yes_price
        if abs(edge) < MACRO_MIN_EDGE:
            continue

        opps.append({
            "market_id":    mkt["market_id"],
            "question":     mkt["question"],
            "event_type":   "NFP",
            "resolves_yes": resolves_yes,
            "model_prob":   model_prob,
            "yes_price":    yes_price,
            "edge":         round(edge, 4),
            "trade_side":   "YES" if resolves_yes else "NO",
            "trade_price":  yes_price if resolves_yes else (1 - yes_price),
            "release_date": str(nfp_data.get("year", "")),
        })

    if not opps:
        _log("NFP: nenhuma oportunidade com edge suficiente")
        return 0

    session_tag = f"NFP_{nfp_data['month']}_{nfp_data['year']}"
    return _process_opportunities(opps, bankroll, session_tag)


# =========================================================
# LOOP PRINCIPAL
# =========================================================

def macro_loop():
    _log("Módulo macro iniciado")
    if not MACRO_TRADING_ENABLED:
        _log("MACRO_TRADING_ENABLED=0 — modo observação")

    last_event_handled = {}

    while True:
        try:
            now    = utcnow()
            active = get_active_windows(now=now)

            if active:
                bankroll = load_bankroll()
                changed  = False

                for window in active:
                    event_key    = window["event"]
                    release_date = window["release_date"]
                    secs_since   = window["secs_since"]
                    post_release = window["post_release"]

                    last = last_event_handled.get(event_key)
                    if last == release_date:
                        continue

                    if not post_release:
                        _log(
                            f"Pré-janela {event_key} | "
                            f"{abs(secs_since):.0f}s até publicação"
                        )
                        continue

                    opened = 0
                    if MACRO_TRADING_ENABLED:
                        if event_key == "CPI":
                            opened = _handle_cpi_window(bankroll, secs_since)
                        elif event_key == "FOMC":
                            opened = _handle_fomc_window(bankroll, secs_since)
                        elif event_key == "NFP":
                            opened = _handle_nfp_window(bankroll, secs_since)
                    else:
                        _log(
                            f"[OBSERVAÇÃO] {event_key} publicado há {secs_since:.0f}s"
                        )
                        real_data = _get_real_data(event_key)
                        if real_data:
                            _log(f"Dado real: {real_data}")
                            try:
                                enviar_mensagem(
                                    f"<b>MACRO DATA [{event_key}]</b>\n\n"
                                    f"<pre>{json.dumps(real_data, indent=2)}</pre>\n"
                                    f"<i>MACRO_TRADING_ENABLED=0 — observação apenas</i>"
                                )
                            except Exception:
                                pass

                    if opened > 0:
                        save_bankroll(bankroll)
                        changed = True

                    last_event_handled[event_key] = release_date

                if changed:
                    _log("Bankroll salvo após trades macro")

                sleep_time = MACRO_POLL_INTERVAL

            else:
                upcoming = get_upcoming_events(days_ahead=7, now=now)
                if upcoming:
                    next_ev = upcoming[0]
                    _log(
                        f"Próximo evento: {next_ev['event']} em "
                        f"{next_ev['hours_ahead']:.1f}h "
                        f"({next_ev['release_date']})"
                    )
                sleep_time = MACRO_IDLE_INTERVAL

        except Exception as e:
            _log(f"ERRO NO LOOP MACRO: {e}")
            traceback.print_exc()
            sleep_time = 60

        time.sleep(sleep_time)


# =========================================================
# INICIALIZAÇÃO (chamada de bot.py)
# =========================================================

def iniciar_macro_bot():
    """Inicia o módulo macro como thread daemon."""
    t = Thread(target=macro_loop, daemon=True)
    t.start()
    return t


# =========================================================
# EXECUÇÃO STANDALONE
# =========================================================

if __name__ == "__main__":
    print("=" * 55)
    print("MACRO BOT — TESTE STANDALONE")
    print("=" * 55)

    upcoming = get_upcoming_events(days_ahead=30)
    print(f"\nPróximos eventos ({len(upcoming)}):")
    for ev in upcoming[:5]:
        print(
            f"  {ev['event']:6} | {ev['release_date']} | "
            f"em {ev['hours_ahead']:.1f}h"
        )

    print("\nBuscando mercados macro na Polymarket...")
    markets = fetch_macro_markets(event_types=["CPI", "FOMC", "NFP"])
    print(f"Encontrados: {len(markets)} mercados")
    for m in markets[:5]:
        print(f"  [{m['event_type']}] {m['question'][:70]}")

    print("\n" + "=" * 55)
    print("Para ativar: MACRO_TRADING_ENABLED=1 no Railway")
    print("=" * 55)
