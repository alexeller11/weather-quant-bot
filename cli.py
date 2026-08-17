#!/usr/bin/env python3
"""Small operations CLI for Weather Quant Bot."""

import argparse
import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://weather-quant-bot.onrender.com"


def _fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "weather-quant-bot-cli/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "weather-quant-bot-cli/1.0"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _local_health() -> dict:
    from dashboard import load_data
    from operational_health import build_operational_health

    data, warning = load_data()
    return build_operational_health(data or {}, warning)


def _local_metrics() -> str:
    from operational_health import build_prometheus_metrics

    return build_prometheus_metrics(_local_health())


def _print_health(health: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(health, indent=2, ensure_ascii=False))
    else:
        print(f"status: {health.get('status')}")
        print(f"summary: {health.get('summary')}")
        print(f"bot_active: {health.get('bot_active')}")
        print(f"db_ok: {health.get('db_ok')} ({health.get('data_source')})")
        print(f"last_decision_age_seconds: {health.get('last_decision_age_seconds')}")
        print(f"dominant_block_reason: {health.get('dominant_block_reason')}")
        print(f"open_count: {health.get('open_count')}")
        print(f"balance: {health.get('balance')}")

    return 0 if health.get("status") not in ("stale", "unknown") else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Weather Quant Bot operations CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    health_p = sub.add_parser("health", help="Print operational health")
    health_p.add_argument("--url", default="", help="Base URL to query instead of local state")
    health_p.add_argument("--json", action="store_true", help="Print raw JSON")

    metrics_p = sub.add_parser("metrics", help="Print Prometheus metrics")
    metrics_p.add_argument("--url", default="", help="Base URL to query instead of local state")

    args = parser.parse_args(argv)

    if args.command == "health":
        if args.url:
            base = args.url.rstrip("/")
            health = _fetch_json(f"{base}/api/health")
        else:
            health = _local_health()
        return _print_health(health, args.json)

    if args.command == "metrics":
        if args.url:
            base = args.url.rstrip("/")
            print(_fetch_text(f"{base}/metrics"), end="")
        else:
            print(_local_metrics(), end="")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
