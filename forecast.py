# =========================================================
# FORECAST ENGINE — OPEN METEO (COM TTL + BIAS CORRECTION)
#
# CORREÇÕES DA AUDITORIA (v5.7):
#
# 1. TIMEZONE: timezone=auto (agregação no dia local da cidade).
#
# 2. CITY_TZ + city_today(): o dia "hoje" é o dia local da cidade.
#
# 3. compute_bias(): deduplicado por (market_date, forecast_day).
#
# AUDITORIA SENIOR:
# 4. Ajustes hardcoded de sigma por cidade removidos de get_forecast.
#    O SigmaCalibrator (agora sempre ativo em model.py) é a fonte
#    correta para correcões por cidade via aprendizado online.
#    Manter os dois causava double-stack do mesmo erro sistemático.
#
# 5. Clamping silencioso corrigido: se forecast_day estiver fora da
#    janela disponível, retorna (None, None) em vez de usar a temperatura
#    do último dia disponível sem avisar.
# =========================================================

import logging
import requests
import time
from datetime import datetime, timezone, timedelta

from config import CITY_COORDS, CITY_TZ, CITY_SLUG_NORMALIZE, FORECAST_RETRIES, FORECAST_RETRY_STATUS

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


def city_now(city_slug):
    """datetime atual no fuso da cidade (fallback: UTC)."""
    tz_name = CITY_TZ.get(city_slug)
    if tz_name and ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now(timezone.utc)


def city_today(city_slug):
    """'Hoje' no fuso da cidade, como string ISO 'YYYY-MM-DD'."""
    return city_now(city_slug).strftime("%Y-%m-%d")


# =========================================================
# BIAS CORRECTION
# =========================================================

BIAS_WINDOW_DAYS = 21
BIAS_MIN_SAMPLES = 3

_BIAS_CACHE = {}
_BIAS_CACHE_TTL = 3600


def _city_raw_to_slug(city_raw, slug_normalize):
    slug = slug_normalize.get(city_raw)
    if slug:
        return slug
    return city_raw.lower().replace(" ", "-").replace("_", "-").strip()


def compute_bias(city_slug):
    """
    Calcula bias medio do Open-Meteo para a cidade.
    bias = mean(forecast_c - real_temp_c) nos trades fechados.
    Cada (market_date, forecast_day) conta UMA vez.
    Retorna (bias_c, n_samples).
    """
    now = time.time()

    cached = _BIAS_CACHE.get(city_slug)
    if cached:
        bias_c, n, computed_at = cached
        if now - computed_at < _BIAS_CACHE_TTL:
            return bias_c, n

    try:
        from bankroll import load_bankroll
    except Exception as e:
        logger.warning(f"[bias] erro ao importar bankroll: {e}")
        return 0.0, 0

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=BIAS_WINDOW_DAYS)

    try:
        history = load_bankroll().get("history", [])
    except Exception as e:
        logger.warning(f"[bias] erro ao carregar bankroll: {e}")
        return 0.0, 0

    samples = {}
    for t in history:
        if t.get("result") not in ("WIN", "LOSS"):
            continue
        if t.get("forecast_c") is None or t.get("real_temp_c") is None:
            continue

        city_raw = t.get("city", "")
        t_slug = _city_raw_to_slug(city_raw, CITY_SLUG_NORMALIZE)
        if t_slug != city_slug:
            continue

        exit_time_str = t.get("exit_time", "")
        if exit_time_str:
            try:
                exit_dt = datetime.fromisoformat(exit_time_str.replace("Z", ""))
                if exit_dt.tzinfo is not None:
                    exit_dt = exit_dt.astimezone(timezone.utc).replace(tzinfo=None)
                if exit_dt < cutoff:
                    continue
            except Exception:
                pass

        err = float(t["forecast_c"]) - float(t["real_temp_c"])
        sample_key = (str(t.get("market_date", "")), int(t.get("forecast_day", 1) or 1))
        samples[sample_key] = err

    errors = list(samples.values())

    if len(errors) < BIAS_MIN_SAMPLES:
        _BIAS_CACHE[city_slug] = (0.0, len(errors), now)
        return 0.0, len(errors)

    bias_c = sum(errors) / len(errors)
    _BIAS_CACHE[city_slug] = (round(bias_c, 3), len(errors), now)

    logger.info(
        f"[bias] {city_slug}: bias={bias_c:+.2f}°C "
        f"({len(errors)} amostras, últimos {BIAS_WINDOW_DAYS}d)"
    )
    return round(bias_c, 3), len(errors)


def get_corrected_forecast(city_slug, forecast_day):
    """
    Retorna (forecast_c_corrigido, raw_sigma, bias_aplicado, forecast_c_raw).

    forecast_c_corrigido = forecast_c_raw - bias
    forecast_c_raw é preservado para evitar feedback loop no compute_bias:
    o bias é calculado comparando previsao crua vs temperatura real, NAO
    comparando previsao corrigida vs real (isso criaria ciclo auto-alimentado).
    """
    raw = get_forecast(city_slug, forecast_day)
    if raw is None or raw[0] is None:
        return None, None, 0.0, None

    forecast_c, raw_sigma = raw
    bias_c, n_samples = compute_bias(city_slug)

    corrected = round(float(forecast_c) - bias_c, 2)

    if bias_c != 0.0:
        logger.info(
            f"[bias] {city_slug} d{forecast_day}: "
            f"{forecast_c:.1f}°C → {corrected:.1f}°C "
            f"(bias={bias_c:+.2f}°C, n={n_samples})"
        )

    return corrected, raw_sigma, bias_c, forecast_c


# =========================================================
# CACHE COM TTL
# =========================================================

_FORECAST_CACHE = {}
_CACHE_TIME     = {}

CACHE_TTL_SECONDS = 3600

# =========================================================
# FORECAST
# =========================================================

def _request_forecast_with_retry(url, params, city_slug):
    """
    GET com retry/backoff para falhas transitorias (429/502/503/504).

    Sem isto, uma unica falha (rate limit por IP compartilhado no plano
    Free do Render, ou hiccup momentaneo da Open-Meteo) descartava o
    mercado inteiro no ciclo — em 2026-08-05 isso chegou a 98.4% das
    tentativas de trade bloqueadas por "forecast indisponivel". O limite
    documentado da Open-Meteo (600 req/min) e' bem folgado para o volume
    do bot, entao a causa mais provavel e' rate limit de IP compartilhado
    entre outros clientes do Render — transitorio por natureza, o que
    torna retry a correcao certa (nao adianta trocar de API).
    """
    last_status = None
    for attempt in range(FORECAST_RETRIES):
        try:
            r = requests.get(url, params=params, timeout=20)
        except Exception as e:
            logger.warning(f"[forecast] {city_slug}: erro de rede (tentativa {attempt+1}/{FORECAST_RETRIES}): {e}")
            last_status = None
        else:
            if r.status_code == 200:
                return r
            last_status = r.status_code
            if r.status_code not in FORECAST_RETRY_STATUS:
                logger.warning(f"[forecast] {city_slug}: erro status={r.status_code}")
                return None

        if attempt < FORECAST_RETRIES - 1:
            backoff = min(2 ** (attempt + 1), 8)
            logger.info(
                f"[forecast] {city_slug}: retry {attempt+1}/{FORECAST_RETRIES} "
                f"em {backoff}s (status={last_status})"
            )
            time.sleep(backoff)

    logger.warning(f"[forecast] {city_slug}: esgotou {FORECAST_RETRIES} tentativas (ultimo status={last_status})")
    return None


def get_forecast(city_slug, forecast_day=1):
    """
    Retorna (forecast_c, raw_sigma) sem correção de bias.
    Use get_corrected_forecast() em bot.py.

    forecast_day: 1 = HOJE (dia local da cidade), 2 = amanhã, ...

    NOTA: sigma retornado e apenas o valor base por horizonte.
    Ajustes por cidade sao responsabilidade do SigmaCalibrator
    (aplicado em model.calculate_probability). Manter ajustes hardcoded
    aqui E no calibrador causava double-stack do mesmo erro sistematico.
    """
    cache_key = (city_slug, forecast_day)
    now       = time.time()

    if cache_key in _FORECAST_CACHE:
        age = now - _CACHE_TIME[cache_key]
        if age < CACHE_TTL_SECONDS:
            return _FORECAST_CACHE[cache_key]
        else:
            del _FORECAST_CACHE[cache_key]
            del _CACHE_TIME[cache_key]

    if city_slug not in CITY_COORDS:
        logger.warning(f"[forecast] cidade desconhecida: {city_slug}")
        return None, None

    lat, lon = CITY_COORDS[city_slug]

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":      lat,
        "longitude":     lon,
        "daily":         "temperature_2m_max",
        "current":       "temperature_2m",
        "timezone":      "auto",
        "forecast_days": 7,
    }

    try:
        r = _request_forecast_with_retry(url, params, city_slug)
        if r is None:
            return None, None

        data = r.json()

        # Verificação de Stale Data (v5.7)
        if "current" in data and "time" in data["current"]:
            try:
                last_update = datetime.fromisoformat(data["current"]["time"].replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - last_update).total_seconds() / 3600
                if age_hours > 6:
                    logger.warning(f"STALE DATA: {city_slug} atualizado ha {age_hours:.1f}h")
            except Exception:
                pass

        if (
            "daily" not in data
            or "temperature_2m_max" not in data["daily"]
        ):
            logger.warning("[forecast] resposta inválida")
            return None, None

        temps = data["daily"]["temperature_2m_max"]

        # CORRIGIDO: antes usava max(0, min(idx, len-1)) que silenciosamente
        # retornava a temperatura do ultimo dia disponivel quando forecast_day
        # estava fora da janela, causando trades com dados fantasma.
        idx = forecast_day - 1
        if idx < 0 or idx >= len(temps) or temps[idx] is None:
            logger.warning(
                f"[forecast] {city_slug} d{forecast_day}: "
                f"fora da janela disponivel ({len(temps)} dias)"
            )
            return None, None

        forecast_c = float(temps[idx])

        # Sigma base por horizonte apenas.
        # Ajustes por cidade sao feitos pelo SigmaCalibrator em model.py.
        # REMOVIDO: blocos hardcoded (+0.40 Houston/Miami, +0.30 Denver/London,
        # +0.50 Chicago) que causavam double-stack com o calibrador online.
        base_sigma_by_day = {1: 4.0, 2: 4.5, 3: 5.0, 4: 5.5, 5: 6.0}
        sigma = base_sigma_by_day.get(forecast_day, 6.0)
        sigma = round(sigma, 2)

        logger.debug(
            f"[forecast] {city_slug} "
            f"forecast={forecast_c:.1f}C sigma_base={sigma:.2f}"
        )

        result = (forecast_c, sigma)
        _FORECAST_CACHE[cache_key] = result
        _CACHE_TIME[cache_key]     = now

        return result

    except Exception as e:
        logger.warning(f"[forecast] erro: {e}")
        return None, None
