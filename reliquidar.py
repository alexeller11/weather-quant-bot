#!/usr/bin/env python3
"""
reliquidar.py — reliquida o histórico contra a resolução OFICIAL do mercado.

POR QUE ISTO EXISTE
-------------------
O histórico atual foi liquidado com a temperatura do Open-Meteo na
coordenada do centro da cidade — que não é a fonte que resolve o mercado
na Polymarket. Em Los Angeles a divergência medida foi de +12.3 °F em
média (12 dias, mínimo +4.0, máximo +18.7) entre a temperatura usada pelo
bot e a temperatura implícita nos preços dos buckets. Consequência: os
buckets negociados (66-85 °F) ficavam sistematicamente fora da faixa da
temperatura "real" do bot (73.8-98.8 °F), e o resultado foi mecânico —
RANGE2/NO ganhou 26/26 e RANGE2/YES perdeu 0/22.

Ou seja: uma parte do histórico está marcada com o resultado INVERTIDO em
relação à realidade. Enquanto não for reliquidado, win rate, ROI, ranking
de cidades e o critério de "110 trades fechados" não medem nada.

COMO FUNCIONA
-------------
Para cada trade fechado, busca o resultado real na Gamma API pelo
`gamma_market_id`: um mercado resolvido tem `umaResolutionStatus`
"resolved" e `outcomePrices` colapsado em ["1","0"] (YES) ou ["0","1"]
(NO). Isso é a verdade contratual do mercado — não uma reconstrução
meteorológica.

Trades sem `gamma_market_id` (26 no histórico, os mais antigos) não são
verificáveis por este caminho e ficam marcados como
`resolution_source: "unverified"`.

USO
---
    python reliquidar.py --dry-run        # relatório, não escreve nada
    python reliquidar.py --apply          # aplica e recalcula o saldo

--apply reescreve bankroll.json e o saldo. Faz backup em
bankroll.pre-reliquidacao.json antes de qualquer escrita.
"""

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("reliquidar")

GAMMA_MARKET_URL = "https://gamma-api.polymarket.com/markets/{}"
BANKROLL_FILE = "bankroll.json"
BACKUP_FILE = "bankroll.pre-reliquidacao.json"
REQUEST_PAUSE = 0.25


def fetch_market_resolution(gamma_market_id: str):
    """
    Retorna 'YES', 'NO' ou None (não resolvido / não verificável).

    A fonte é o próprio mercado: preço final colapsado em 1/0.
    """
    if not gamma_market_id:
        return None
    try:
        r = requests.get(
            GAMMA_MARKET_URL.format(gamma_market_id),
            headers={"User-Agent": "weather-quant-bot/reliquidar"},
            timeout=15,
        )
        if r.status_code != 200:
            logger.warning("market %s: HTTP %s", gamma_market_id, r.status_code)
            return None
        m = r.json()
    except Exception as exc:
        logger.warning("market %s: %s", gamma_market_id, exc)
        return None

    if not (m.get("closed") or str(m.get("umaResolutionStatus", "")).lower() == "resolved"):
        return None

    raw = m.get("outcomePrices")
    if not raw:
        return None
    try:
        prices = json.loads(raw) if isinstance(raw, str) else list(raw)
        yes = float(prices[0])
    except Exception:
        return None

    if yes >= 0.99:
        return "YES"
    if yes <= 0.01:
        return "NO"
    return None


def recompute(trade: dict, market_yes: bool) -> dict:
    """Recalcula result/pnl/fee a partir da resolução oficial."""
    from config import FEE_RATE

    side = str(trade.get("side") or "YES").upper()
    won = market_yes if side == "YES" else (not market_yes)

    stake = float(trade.get("stake") or 0)
    entry_price = float(trade.get("entry_price") or trade.get("market_price") or 0)
    shares = trade.get("shares")

    out = dict(trade)
    if won:
        if shares:
            gross = float(shares)
        elif entry_price > 0:
            gross = stake / entry_price
        else:
            gross = 0.0
        fee = round(gross * FEE_RATE, 4)
        out["result"] = "WIN"
        out["fee"] = fee
        out["pnl"] = round(gross - stake - fee, 4)
    else:
        out["result"] = "LOSS"
        out["fee"] = 0.0
        out["pnl"] = round(-stake, 4)

    out["market_yes"] = bool(market_yes)
    out["resolution_source"] = "polymarket"
    out["reliquidado_em"] = datetime.now(timezone.utc).isoformat()
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="só relatório")
    g.add_argument("--apply", action="store_true", help="reescreve o bankroll")
    ap.add_argument("--file", default=BANKROLL_FILE)
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)

    history = data.get("history", [])
    closed = [t for t in history if t.get("result") in ("WIN", "LOSS")]
    logger.info("%d trades fechados a verificar", len(closed))

    stats = Counter()
    changes = []
    new_history = []

    for t in history:
        if t.get("result") not in ("WIN", "LOSS"):
            new_history.append(t)
            continue

        gid = str(t.get("gamma_market_id") or "").strip()
        if not gid:
            t = dict(t)
            t["resolution_source"] = "unverified"
            stats["sem_gamma_market_id"] += 1
            new_history.append(t)
            continue

        resolution = fetch_market_resolution(gid)
        time.sleep(REQUEST_PAUSE)

        if resolution is None:
            t = dict(t)
            t["resolution_source"] = "unverified"
            stats["nao_resolvido_na_api"] += 1
            new_history.append(t)
            continue

        rebuilt = recompute(t, resolution == "YES")
        if rebuilt["result"] != t.get("result"):
            stats["INVERTIDO"] += 1
            changes.append((t, rebuilt))
        else:
            stats["confirmado"] += 1
        new_history.append(rebuilt)

    print()
    print("=" * 72)
    for k, v in stats.most_common():
        print(f"  {k:24} {v}")

    old_pnl = sum(float(t.get("pnl") or 0) for t in history
                  if t.get("result") in ("WIN", "LOSS"))
    new_pnl = sum(float(t.get("pnl") or 0) for t in new_history
                  if t.get("result") in ("WIN", "LOSS"))
    print("=" * 72)
    print(f"  PnL antes : {old_pnl:+.2f}")
    print(f"  PnL depois: {new_pnl:+.2f}   (delta {new_pnl - old_pnl:+.2f})")

    if changes:
        print()
        print("  Trades cujo resultado INVERTEU:")
        for old, new in changes[:40]:
            print(f"    {old.get('market_date')} {old.get('city','?'):14} "
                  f"{old.get('type','?'):6} {old.get('side','?'):3} "
                  f"{old.get('result')} -> {new['result']}  "
                  f"pnl {float(old.get('pnl') or 0):+.2f} -> {new['pnl']:+.2f}")
        if len(changes) > 40:
            print(f"    ... e mais {len(changes) - 40}")

    if args.dry_run:
        print()
        print("  DRY-RUN — nada foi escrito.")
        return 0

    # --apply
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    logger.info("backup gravado em %s", BACKUP_FILE)

    start = float(data.get("start_balance", 0))
    open_stakes = sum(float(t.get("stake") or 0) for t in new_history
                      if t.get("result") == "OPEN")
    data["history"] = new_history
    data["balance"] = round(start - open_stakes + new_pnl, 4)
    data["seq"] = int(data.get("seq", 0)) + 1
    data["saved_at"] = datetime.now(timezone.utc).isoformat()
    data["reliquidacao_note"] = (
        "Historico reliquidado contra a resolucao oficial da Polymarket. "
        "Trades marcados resolution_source=unverified nao foram verificaveis."
    )

    tmp = args.file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, args.file)

    print()
    print(f"  APLICADO. Novo saldo: ${data['balance']:.2f}")
    print("  Rode `python -c \"import bankroll,json;"
          "print(bankroll.check_balance_invariant(json.load(open('bankroll.json'))))\"`"
          " para conferir a invariante.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
