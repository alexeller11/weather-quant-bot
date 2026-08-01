#!/usr/bin/env python3
"""
sigma_calibrator.py — Calibração de Sigma por Cidade

v4 — o sigma agora é ESTIMADO, não "ajustado para cima".

A versão anterior calculava
    adjustment = max(0.0, (media_ponderada_do_erro_absoluto - 2.0) * 0.6)
e somava ao sigma base. Duas consequências:

  1. O ajuste era unilateral: `max(0.0, ...)` só sabia AUMENTAR o sigma.
  2. Com o erro absoluto médio observado de 1.50°C (102 pares
     forecast/real), `media - 2.0` é sempre negativo → adjustment = 0
     sempre. Em 132 trades o sigma gravado foi 4.0 (51x), 4.5 (51x),
     5.0 (3x) e 4.3 (1x): o calibrador nunca mexeu em nada.

Resultado: o modelo operou com sigma de 4.0–6.0°C quando o desvio-padrão
real dos resíduos era 1.72°C — 2.3x a 3.5x mais largo. Sigma inflado
achata a probabilidade dos buckets estreitos perto da previsão e engorda
a cauda distante, que é exatamente o viés que empurra o bot a vender
buckets prováveis e comprar buckets improváveis.

Agora guardamos o resíduo COM SINAL e estimamos sigma = desvio-padrão
ponderado dos resíduos, com shrinkage para o sigma base:

    peso  = n / (n + SIGMA_SHRINK_K)
    sigma = peso * sigma_empirico + (1 - peso) * sigma_base

Isto converge para o erro real e pode ajustar em ambas as direções.
"""

import json
import math
import os
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
import unicodedata

from config import SIGMA_MIN, SIGMA_MAX, SIGMA_MIN_SAMPLES, SIGMA_SHRINK_K

logger = logging.getLogger(__name__)

SIGMA_CALIBRATION_FILE = "sigma_calibration.json"
_DB_KEY = "sigma_calibration_v2"

# AUDITORIA bug #2: TTL de recarga para mitigar stale cross-process.
# settlement.py gravava actualizacoes; o bot (processo separado) nunca
# via-as. Espelha o padrao do ml_adjuster (1h). 0 = desativado.
_CALIBRATOR_CACHE_TTL = int(os.getenv("SIGMA_CALIBRATOR_TTL", "3600"))


def _strip_accents(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _decay_weights(n: int, decay: float = 0.9) -> List[float]:
    """Observações recentes pesam mais."""
    return [decay ** (n - 1 - i) for i in range(n)]


def _empirical_sigma(entries: List[dict]):
    """
    Desvio-padrão ponderado dos resíduos de previsão, em °C.

    Retorna (sigma, n) ou (None, n) quando há amostra insuficiente.

    Prefere o resíduo COM SINAL ("residual"). Registos gravados antes da
    v4 só têm o erro absoluto: nesse caso usa o RMS de |erro|, que é um
    limite SUPERIOR do desvio-padrão — conservador, e converge para o
    valor correto conforme entram observações novas.
    """
    signed = [e for e in entries if isinstance(e, dict) and e.get("residual") is not None]
    if len(signed) >= SIGMA_MIN_SAMPLES:
        vals = [float(e["residual"]) for e in signed]
        n = len(vals)
        w = _decay_weights(n)
        w_sum = sum(w)
        mean = sum(wi * v for wi, v in zip(w, vals)) / w_sum
        var = sum(wi * (v - mean) ** 2 for wi, v in zip(w, vals)) / w_sum
        if n > 1:
            var *= n / (n - 1.0)   # correção de viés para amostra pequena
        return math.sqrt(var), n

    vals = [
        abs(float(e["error"])) for e in entries
        if isinstance(e, dict) and e.get("error") is not None
    ]
    n = len(vals)
    if n < SIGMA_MIN_SAMPLES:
        return None, n
    w = _decay_weights(n)
    w_sum = sum(w)
    rms = math.sqrt(sum(wi * v * v for wi, v in zip(w, vals)) / w_sum)
    return rms, n


class SigmaCalibrator:
    def __init__(self):
        self.calibration_data: Dict = self._load()
        self._loaded_at: float = time.time()

    def _maybe_reload(self):
        """AUDITORIA bug #2: recarrega do DB/file se o cache expirou.

        settlement.py e bot.py sao processos separados (Railway): sem
        isto, o bot grava no seu RAM um snapshot cold-load nunca mais
        atualizado — calibracao write-only entre restarts.
        """
        if _CALIBRATOR_CACHE_TTL <= 0:
            return
        if time.time() - self._loaded_at < _CALIBRATOR_CACHE_TTL:
            return
        fresh = self._load()
        if fresh:
            self.calibration_data = fresh
            self._loaded_at = time.time()
            logger.debug("[sigma] calibracao recarregada (TTL expirou)")

    # ── persistência ─────────────────────────────────────────

    def _load(self) -> Dict:
        data = self._load_from_db()
        if data:
            return data
        if os.path.exists(SIGMA_CALIBRATION_FILE):
            try:
                with open(SIGMA_CALIBRATION_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"sigma_calibration.json corrompido: {e}")
        return {}

    def _load_from_db(self) -> Dict:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return {}
        try:
            import psycopg2
            conn = psycopg2.connect(url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kv_store (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        saved_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                conn.commit()
                cur.execute("SELECT value FROM kv_store WHERE key = %s", (_DB_KEY,))
                row = cur.fetchone()
            conn.close()
            return row[0] if row else {}
        except Exception as e:
            logger.debug(f"[sigma] db load: {e}")
            return {}

    def _save(self):
        try:
            with open(SIGMA_CALIBRATION_FILE, "w", encoding="utf-8") as f:
                json.dump(self.calibration_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"sigma_calibration.json save: {e}")

        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return
        try:
            import psycopg2
            conn = psycopg2.connect(url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kv_store (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        saved_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    INSERT INTO kv_store (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value, saved_at = NOW()
                """, (_DB_KEY, json.dumps(self.calibration_data)))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[sigma] db save: {e}")

    # ── API pública ───────────────────────────────────────────

    def record_trade_result(
        self,
        city: str,
        day_offset: int,
        predicted_temp: float,
        actual_temp: float,
        condition: str = "ABOVE",
        market_date: str = None,
    ):
        """
        Registra UMA observação de erro de forecast.

        market_date (opcional, "YYYY-MM-DD"): identifica o dia do mercado.
        Quando informado, observações repetidas para o mesmo
        (cidade, condição, market_date) são ignoradas — vários buckets do
        mesmo evento liquidados juntos representam UM único erro de
        forecast, não N erros independentes.
        """
        # AUDITORIA bug #10: normalizacao com strip de acentos — igual
        # ao get_adjusted_sigma e ao bankroll.normalize_city_slug.
        city_key = _strip_accents(city).strip().lower().replace(" ", "-")
        # residuo COM SINAL (previsto - real). O absoluto continua gravado
        # em "error" para compatibilidade com dados antigos e com o
        # ml_adjuster, mas a estimativa de sigma usa o residuo assinado.
        residual = float(predicted_temp) - float(actual_temp)
        error    = abs(residual)
        cond_key = condition.upper()

        if city_key not in self.calibration_data:
            self.calibration_data[city_key] = {}

        if cond_key not in self.calibration_data[city_key]:
            self.calibration_data[city_key][cond_key] = {
                "errors": [],
                "sigma_empirical": None,
            }

        errors_list = self.calibration_data[city_key][cond_key]["errors"]

        # Dedup por dia de mercado: o erro do forecast de um dia é um
        # evento único, independentemente de quantos trades existiam nele.
        if market_date:
            for e in errors_list:
                if e.get("market_date") == market_date:
                    logger.debug(
                        f"[sigma] {city_key}/{cond_key} {market_date}: "
                        f"amostra já registrada — ignorando duplicata"
                    )
                    return

        entry = {
            "day_offset": day_offset,
            "error":      round(error, 2),
            "residual":   round(residual, 2),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        if market_date:
            entry["market_date"] = market_date
        errors_list.append(entry)

        # Janela máxima de 40 observações
        self.calibration_data[city_key][cond_key]["errors"] = errors_list[-40:]

        # Recalcula o sigma empírico com decaimento temporal
        errors_list = self.calibration_data[city_key][cond_key]["errors"]
        sigma_emp, n = _empirical_sigma(errors_list)
        if sigma_emp is not None:
            self.calibration_data[city_key][cond_key]["sigma_empirical"] = round(sigma_emp, 3)
            logger.info(
                f"[sigma] {city_key}/{cond_key} d{day_offset}: "
                f"residuo={residual:+.1f}°C sigma_empirico={sigma_emp:.2f}°C (n={n})"
            )

        self._save()

    def get_adjusted_sigma(
        self,
        city: str,
        base_sigma: float,
        condition: str = "ABOVE",
    ) -> float:
        self._maybe_reload()
        # AUDITORIA bug #10: strip accents na chave — igual ao
        # bankroll.normalize_city_slug. Sem isto, callers que passassem
        # "São Paulo" vs "são paulo" vs "sao-paulo" dividiriam a
        # calibracao em 3 buckets não relacionados.
        city_key = _strip_accents(city).strip().lower().replace(" ", "-")
        cond_key = condition.upper()

        cond_data = (
            self.calibration_data
            .get(city_key, {})
            .get(cond_key, {})
        )

        sigma_emp, n = _empirical_sigma(cond_data.get("errors", []))

        if sigma_emp is None:
            # Amostra insuficiente: fica no sigma base, sem inventar.
            sigma = float(base_sigma)
        else:
            # Shrinkage para o base: peso cresce com a amostra.
            weight = n / (n + SIGMA_SHRINK_K)
            sigma = weight * sigma_emp + (1.0 - weight) * float(base_sigma)

        sigma = max(SIGMA_MIN, min(SIGMA_MAX, sigma))
        return round(sigma, 4)

    def get_recent_errors(
        self,
        city: str,
        condition: Optional[str] = None,
    ) -> List[float]:
        """
        Lista de erros recentes (float, °C) para a cidade.
        """
        self._maybe_reload()
        city_key = _strip_accents(city).strip().lower().replace(" ", "-")
        conds = self.calibration_data.get(city_key, {})
        if not isinstance(conds, dict):
            return []

        if condition is not None:
            data = conds.get(condition.upper(), {})
            entries = data.get("errors", []) if isinstance(data, dict) else []
            return [
                float(e["error"]) for e in entries
                if isinstance(e, dict) and "error" in e
            ]

        merged = []
        for data in conds.values():
            if isinstance(data, dict):
                for e in data.get("errors", []):
                    if isinstance(e, dict) and "error" in e:
                        merged.append((e.get("timestamp", ""), float(e["error"])))
        merged.sort(key=lambda t: t[0])
        return [v for _, v in merged]

    def resumo_calibracao(self) -> str:
        """Retorna resumo legível da calibração atual por cidade."""
        linhas = []
        for city, conds in sorted(self.calibration_data.items()):
            for cond, data in conds.items():
                entries = data.get("errors", [])
                n = len(entries)
                if not n:
                    continue
                erros = [e["error"] for e in entries if e.get("error") is not None]
                media = sum(erros) / len(erros) if erros else 0.0
                sigma_emp, n_used = _empirical_sigma(entries)
                sigma_txt = f"{sigma_emp:.2f}°C" if sigma_emp is not None else "n/d"
                linhas.append(
                    f"  {city}/{cond}: n={n} err_med={media:.1f}°C "
                    f"sigma_empirico={sigma_txt} (n_util={n_used})"
                )
        return "\n".join(linhas) if linhas else "  sem dados ainda"
