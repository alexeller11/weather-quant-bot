"""
GITHUB SYNC — WEATHER QUANT
Auto-commit do bankroll.json para o repositório GitHub após cada save.
Isso garante que o saldo sobrevive a qualquer redeploy no Railway.

Configuração necessária no .env / Railway Variables:
    GITHUB_TOKEN  — Personal Access Token com permissão "repo"
    GITHUB_REPO   — ex: seu_usuario/weather-quant-bot
    GITHUB_BRANCH — branch alvo, normalmente "main"
"""

import os
import json
import base64
import requests
from datetime import datetime, timezone

from config import TELEGRAM_TOKEN  # só para checar que .env está carregado

GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO   = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
BANKROLL_FILE = "bankroll.json"

_API = "https://api.github.com"
_HEADERS = lambda: {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}


def _configurado():
    return bool(GITHUB_TOKEN and GITHUB_REPO)


def _get_sha_atual():
    """Pega o SHA do bankroll.json atual no repo (necessário para atualizar)."""
    url = f"{_API}/repos/{GITHUB_REPO}/contents/{BANKROLL_FILE}"
    r = requests.get(url, headers=_HEADERS(), params={"ref": GITHUB_BRANCH}, timeout=10)
    if r.status_code == 200:
        return r.json().get("sha")
    return None  # arquivo não existe ainda — primeira vez


def commit_bankroll(bankroll_data):
    """
    Faz commit do bankroll.json no GitHub.
    Chamado automaticamente após todo save_bankroll().
    Retorna True se ok, False se falhou (não interrompe o bot).
    """
    if not _configurado():
        return False

    try:
        conteudo = json.dumps(bankroll_data, indent=4, ensure_ascii=False)
        conteudo_b64 = base64.b64encode(conteudo.encode()).decode()

        sha = _get_sha_atual()

        saldo = bankroll_data.get("balance", 0)
        abertos = len([t for t in bankroll_data.get("history", []) if t.get("result") == "OPEN"])
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        mensagem_commit = f"bankroll: ${saldo:.2f} | {abertos} abertos | {ts}"

        payload = {
            "message": mensagem_commit,
            "content": conteudo_b64,
            "branch":  GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        url = f"{_API}/repos/{GITHUB_REPO}/contents/{BANKROLL_FILE}"
        r = requests.put(url, headers=_HEADERS(), json=payload, timeout=15)

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
    if not _configurado():
        return False
    try:
        conteudo     = json.dumps(validacao_data, indent=2, ensure_ascii=False)
        conteudo_b64 = base64.b64encode(conteudo.encode()).decode()
        r = requests.get(
            f"{_API}/repos/{GITHUB_REPO}/contents/validacao.json",
            headers=_HEADERS(), params={"ref": GITHUB_BRANCH}, timeout=10,
        )
        sha = r.json().get("sha") if r.status_code == 200 else None
        n   = len(validacao_data.get("previsoes", []))
        payload = {
            "message": f"validacao: {n} previsoes",
            "content": conteudo_b64,
            "branch":  GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        r2 = requests.put(
            f"{_API}/repos/{GITHUB_REPO}/contents/validacao.json",
            headers=_HEADERS(), json=payload, timeout=15,
        )
        return r2.status_code in (200, 201)
    except Exception as e:
        print(f"  [github] validacao erro: {e}")
        return False
