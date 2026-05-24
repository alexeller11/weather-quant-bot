"""
GITHUB SYNC - WEATHER QUANT

Reads GitHub credentials at call time so Railway-injected environment
variables are available after process start.
"""

# Deploy marker: sync guard active.

import os
import json
import base64
import requests
from datetime import datetime, timezone

BANKROLL_FILE = "bankroll.json"
_API = "https://api.github.com"


def _get_config():
    """Read config from the environment on each call."""
    return {
        "token": os.environ.get("GITHUB_TOKEN", "").strip(),
        "repo": os.environ.get("GITHUB_REPO", "").strip(),
        "branch": os.environ.get("GITHUB_BRANCH", "main").strip(),
    }


def _headers(token):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _configurado():
    cfg = _get_config()
    return bool(cfg["token"] and cfg["repo"])


def _get_remote_file(token, repo, branch, path):
    url = f"{_API}/repos/{repo}/contents/{path}"
    try:
        r = requests.get(
            url,
            headers=_headers(token),
            params={"ref": branch},
            timeout=10,
        )
        if r.status_code == 200:
            payload = r.json()
            content = base64.b64decode(payload.get("content", "")).decode()
            return payload.get("sha"), content
    except Exception:
        pass
    return None


def _get_sha_atual(token, repo, branch):
    """Get the current bankroll.json blob SHA."""
    remote = _get_remote_file(token, repo, branch, BANKROLL_FILE)
    if remote:
        return remote[0]
    return None


def commit_bankroll(bankroll_data):
    """
    Commit bankroll.json to GitHub.
    Returns True if saved or already up to date, False on failure.
    """
    cfg = _get_config()
    if not cfg["token"] or not cfg["repo"]:
        return False

    token = cfg["token"]
    repo = cfg["repo"]
    branch = cfg["branch"]

    try:
        conteudo = json.dumps(bankroll_data, indent=4, ensure_ascii=False)
        conteudo_b64 = base64.b64encode(conteudo.encode()).decode()

        saldo = bankroll_data.get("balance", 0)
        abertos = len([
            t for t in bankroll_data.get("history", [])
            if t.get("result") == "OPEN"
        ])
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        payload = {
            "message": f"bankroll: ${saldo:.2f} | {abertos} abertos | {ts}",
            "content": conteudo_b64,
            "branch": branch,
        }

        for tentativa in range(2):
            remote = _get_remote_file(token, repo, branch, BANKROLL_FILE)
            if remote:
                sha, remote_content = remote
                if remote_content == conteudo:
                    print("  [github] bankroll sem alteracoes")
                    return True
                payload["sha"] = sha
            elif "sha" in payload:
                del payload["sha"]

            r = requests.put(
                f"{_API}/repos/{repo}/contents/{BANKROLL_FILE}",
                headers=_headers(token),
                json=payload,
                timeout=15,
            )

            if r.status_code in (200, 201):
                print(f"  [github] bankroll salvo: ${saldo:.2f}")
                return True

            if r.status_code == 409 and tentativa == 0:
                print("  [github] conflito de SHA, tentando novamente...")
                continue

            print(f"  [github] erro {r.status_code}: {r.text[:200]}")
            return False

    except Exception as e:
        print(f"  [github] excecao: {e}")
        return False


def commit_validacao(validacao_data):
    """Commit validacao.json to GitHub."""
    cfg = _get_config()
    if not cfg["token"] or not cfg["repo"]:
        return False

    token = cfg["token"]
    repo = cfg["repo"]
    branch = cfg["branch"]

    try:
        conteudo = json.dumps(validacao_data, indent=2, ensure_ascii=False)
        conteudo_b64 = base64.b64encode(conteudo.encode()).decode()

        remote = _get_remote_file(token, repo, branch, "validacao.json")
        sha = remote[0] if remote else None
        n = len(validacao_data.get("previsoes", []))

        payload = {
            "message": f"validacao: {n} previsoes",
            "content": conteudo_b64,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        r2 = requests.put(
            f"{_API}/repos/{repo}/contents/validacao.json",
            headers=_headers(token),
            json=payload,
            timeout=15,
        )
        return r2.status_code in (200, 201)

    except Exception as e:
        print(f"  [github] validacao erro: {e}")
        return False
