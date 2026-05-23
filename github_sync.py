"""
GITHUB SYNC — WEATHER QUANT
FIX: GITHUB_TOKEN agora lido dentro das funções (não no import-time).
Isso resolve o erro 403 quando o Railway injeta vars após o processo iniciar.
"""

import os
import json
import base64
import requests
from datetime import datetime, timezone

BANKROLL_FILE = "bankroll.json"
_API = "https://api.github.com"


def _get_config():
    """Lê config do ambiente a cada chamada — garante valor atualizado."""
    return {
        "token":  os.environ.get("GITHUB_TOKEN", "").strip(),
        "repo":   os.environ.get("GITHUB_REPO", "").strip(),
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


def _get_sha_atual(token, repo, branch):
    """Pega o SHA do bankroll.json atual no repo."""
    url = f"{_API}/repos/{repo}/contents/{BANKROLL_FILE}"
    try:
        r = requests.get(url, headers=_headers(token),
                         params={"ref": branch}, timeout=10)
        if r.status_code == 200:
            return r.json().get("sha")
    except Exception:
        pass
    return None


def commit_bankroll(bankroll_data):
    """
    Faz commit do bankroll.json no GitHub.
    Retorna True se ok, False se falhou.
    """
    cfg = _get_config()
    if not cfg["token"] or not cfg["repo"]:
        return False

    token  = cfg["token"]
    repo   = cfg["repo"]
    branch = cfg["branch"]

    try:
        conteudo     = json.dumps(bankroll_data, indent=4, ensure_ascii=False)
        conteudo_b64 = base64.b64encode(conteudo.encode()).decode()
        sha          = _get_sha_atual(token, repo, branch)

        saldo   = bankroll_data.get("balance", 0)
        abertos = len([t for t in bankroll_data.get("history", [])
                       if t.get("result") == "OPEN"])
        ts      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        payload = {
            "message": f"bankroll: ${saldo:.2f} | {abertos} abertos | {ts}",
            "content": conteudo_b64,
            "branch":  branch,
        }
        if sha:
            payload["sha"] = sha

        r = requests.put(
            f"{_API}/repos/{repo}/contents/{BANKROLL_FILE}",
            headers=_headers(token),
            json=payload,
            timeout=15,
        )

        if r.status_code in (200, 201):
            print(f"  [github] bankroll salvo: ${saldo:.2f}")
            return True
        else:
            print(f"  [github] erro {r.status_code}: {r.text[:200]}")
            return False

    except Exception as e:
        print(f"  [github] exceção: {e}")
        return False


def commit_validacao(validacao_data):
    """Commit do validacao.json no GitHub."""
    cfg = _get_config()
    if not cfg["token"] or not cfg["repo"]:
        return False

    token  = cfg["token"]
    repo   = cfg["repo"]
    branch = cfg["branch"]

    try:
        conteudo     = json.dumps(validacao_data, indent=2, ensure_ascii=False)
        conteudo_b64 = base64.b64encode(conteudo.encode()).decode()

        r = requests.get(
            f"{_API}/repos/{repo}/contents/validacao.json",
            headers=_headers(token),
            params={"ref": branch},
            timeout=10,
        )
        sha = r.json().get("sha") if r.status_code == 200 else None
        n   = len(validacao_data.get("previsoes", []))

        payload = {
            "message": f"validacao: {n} previsoes",
            "content": conteudo_b64,
            "branch":  branch,
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
