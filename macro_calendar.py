"""
macro_calendar.py — Calendário de eventos econômicos dos EUA.

Fontes públicas e gratuitas:
  - BLS (Bureau of Labor Statistics): CPI, NFP, Desemprego
  - FRED (Federal Reserve): dados históricos
  - BEA (Bureau of Economic Analysis): GDP

Horários de publicação (Eastern Time, convertidos para UTC):
  - CPI:  8:30 AM ET  → 13:30 UTC (verão) / 12:30 UTC (inverno)
  - NFP:  8:30 AM ET  → 13:30 UTC (verão) / 12:30 UTC (inverno)
  - FOMC: 14:00 ET    → 18:00 UTC (verão) / 19:00 UTC (inverno)

Estratégia: monitorar 5 minutos antes até 10 minutos após publicação.
A janela de ineficiência real é de 30 segundos a 3 minutos após o dado sair.
"""

from datetime import datetime, timezone, timedelta, date
import calendar as cal

# =========================================================
# EVENTOS MONITORADOS
# =========================================================

MACRO_EVENTS = {
    "CPI": {
        "name":        "Consumer Price Index",
        "source":      "BLS",
        "release_hour_utc": 13,   # 8:30 AM ET verão
        "release_min_utc":  30,
        "window_before_min": 5,   # começa a monitorar 5 min antes
        "window_after_min":  8,   # para de monitorar 8 min após
        "frequency":   "monthly",
        "description": "CPI mensal (YoY e MoM) — alta volatilidade",
    },
    "NFP": {
        "name":        "Nonfarm Payrolls",
        "source":      "BLS",
        "release_hour_utc": 13,
        "release_min_utc":  30,
        "window_before_min": 5,
        "window_after_min":  8,
        "frequency":   "monthly_first_friday",
        "description": "Empregos não-agrícolas + taxa de desemprego",
    },
    "FOMC": {
        "name":        "FOMC Rate Decision",
        "source":      "FED",
        "release_hour_utc": 18,   # 2:00 PM ET verão
        "release_min_utc":  0,
        "window_before_min": 3,
        "window_after_min":  10,
        "frequency":   "8x_year",
        "description": "Decisão de juros do Fed — mercados de Fed Rate",
    },
    "GDP": {
        "name":        "GDP Advance Estimate",
        "source":      "BEA",
        "release_hour_utc": 13,
        "release_min_utc":  30,
        "window_before_min": 5,
        "window_after_min":  8,
        "frequency":   "quarterly",
        "description": "PIB trimestral — estimativa preliminar",
    },
}

# =========================================================
# PRÓXIMAS DATAS DE PUBLICAÇÃO
# Tabela fixa para 2026 — atualizar anualmente ou via scraper.
# Fonte: https://www.bls.gov/schedule/news_release/cpi.htm
#        https://www.bls.gov/schedule/news_release/empsit.htm
# =========================================================

RELEASE_DATES_2026 = {
    "CPI": [
        date(2026, 1, 14),
        date(2026, 2, 11),
        date(2026, 3, 11),
        date(2026, 4, 10),
        date(2026, 5, 12),
        date(2026, 6, 10),
        date(2026, 7, 14),
        date(2026, 8, 12),
        date(2026, 9, 10),
        date(2026, 10, 13),
        date(2026, 11, 12),
        date(2026, 12, 10),
    ],
    "NFP": [
        date(2026, 1, 9),
        date(2026, 2, 6),
        date(2026, 3, 6),
        date(2026, 4, 3),
        date(2026, 5, 1),
        date(2026, 6, 5),
        date(2026, 7, 10),
        date(2026, 8, 7),
        date(2026, 9, 4),
        date(2026, 10, 2),
        date(2026, 11, 6),
        date(2026, 12, 4),
    ],
    "FOMC": [
        date(2026, 1, 29),
        date(2026, 3, 18),
        date(2026, 5, 7),
        date(2026, 6, 17),
        date(2026, 7, 29),
        date(2026, 9, 16),
        date(2026, 10, 28),
        date(2026, 12, 9),
    ],
    "GDP": [
        date(2026, 1, 29),   # Q4 2025 advance
        date(2026, 4, 29),   # Q1 2026 advance
        date(2026, 7, 30),   # Q2 2026 advance
        date(2026, 10, 29),  # Q3 2026 advance
    ],
}


# =========================================================
# HELPERS
# =========================================================

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_release_datetime(event_key, release_date):
    """
    Retorna datetime UTC exato da publicação do dado.
    """
    ev = MACRO_EVENTS[event_key]
    return datetime(
        release_date.year,
        release_date.month,
        release_date.day,
        ev["release_hour_utc"],
        ev["release_min_utc"],
        0,
    )


def is_in_trading_window(event_key, release_date, now=None):
    """
    Verifica se estamos dentro da janela de monitoramento do evento.
    Retorna (bool, seconds_to_release, seconds_since_release).
    """
    if now is None:
        now = utcnow()

    release_dt = get_release_datetime(event_key, release_date)
    ev = MACRO_EVENTS[event_key]

    window_start = release_dt - timedelta(minutes=ev["window_before_min"])
    window_end   = release_dt + timedelta(minutes=ev["window_after_min"])

    in_window = window_start <= now <= window_end
    seconds_to = (release_dt - now).total_seconds()
    seconds_since = (now - release_dt).total_seconds()

    return in_window, seconds_to, seconds_since


def get_upcoming_events(days_ahead=7, now=None):
    """
    Retorna lista de eventos nos próximos N dias.
    """
    if now is None:
        now = utcnow()

    upcoming = []
    today = now.date()
    cutoff = today + timedelta(days=days_ahead)

    for event_key, dates in RELEASE_DATES_2026.items():
        for release_date in dates:
            if today <= release_date <= cutoff:
                release_dt = get_release_datetime(event_key, release_date)
                upcoming.append({
                    "event":        event_key,
                    "name":         MACRO_EVENTS[event_key]["name"],
                    "release_date": release_date,
                    "release_dt":   release_dt,
                    "hours_ahead":  (release_dt - now).total_seconds() / 3600,
                })

    return sorted(upcoming, key=lambda x: x["release_dt"])


def get_active_windows(now=None):
    """
    Retorna eventos cuja janela de trading está ativa agora.
    """
    if now is None:
        now = utcnow()

    active = []
    today = now.date()

    for event_key, dates in RELEASE_DATES_2026.items():
        for release_date in dates:
            if abs((release_date - today).days) > 1:
                continue
            in_window, secs_to, secs_since = is_in_trading_window(
                event_key, release_date, now
            )
            if in_window:
                active.append({
                    "event":         event_key,
                    "name":          MACRO_EVENTS[event_key]["name"],
                    "release_date":  release_date,
                    "release_dt":    get_release_datetime(event_key, release_date),
                    "secs_to":       secs_to,
                    "secs_since":    secs_since,
                    "post_release":  secs_since > 0,
                })

    return active


if __name__ == "__main__":
    print("=" * 55)
    print("MACRO CALENDAR — PRÓXIMOS EVENTOS")
    print("=" * 55)
    upcoming = get_upcoming_events(days_ahead=30)
    if not upcoming:
        print("Nenhum evento nos próximos 30 dias")
    for ev in upcoming:
        print(
            f"  {ev['event']:6} | {ev['release_date']} | "
            f"{ev['release_dt'].strftime('%H:%M UTC')} | "
            f"em {ev['hours_ahead']:.1f}h"
        )

    print("\nJanelas ativas agora:")
    active = get_active_windows()
    if not active:
        print("  Nenhuma janela ativa")
    for ev in active:
        status = "PÓS" if ev["post_release"] else "PRÉ"
        print(f"  {ev['event']} [{status}] — {abs(ev['secs_since']):.0f}s desde publicação")
