def load_data():
    """
    Carrega bankroll APENAS de fontes compartilhadas entre worker e web.

    FIX #11: Tratamento melhor de DATABASE_URL vazio vs faltando.
    """
    errors = []

    # ── 1. PostgreSQL (fonte principal — atualizada pelo bot.py) ──────────────
    db_url = os.environ.get("DATABASE_URL")
    
    if db_url is None:
        errors.append("DATABASE_URL não configurada")
    elif not db_url.strip():
        errors.append("DATABASE_URL está vazia")
    else:
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, sslmode="require")
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM bankroll ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
            conn.close()
            if row:
                print(f"[dashboard] Dados carregados do PostgreSQL — "
                      f"saldo ${row[0].get('balance', 0):.2f}")
                return row[0], None
            else:
                errors.append("PostgreSQL conectado mas sem registros na tabela bankroll")
        except Exception as e:
            errors.append(f"PostgreSQL erro: {e}")
            print(f"[dashboard] DB erro: {e}")

    # ── 2. GitHub (backup externo) ────────────────────────────────────────────
    try:
        token  = os.environ.get("GITHUB_TOKEN", "")
        repo   = os.environ.get("GITHUB_REPO", "")
        branch = os.environ.get("GITHUB_BRANCH", "main")
        if token and repo:
            import requests as req
            r = req.get(
                f"https://api.github.com/repos/{repo}/contents/bankroll.json",
                headers={"Authorization": f"token {token}"},
                params={"ref": branch},
                timeout=10,
            )
            if r.status_code == 200:
                conteudo = base64.b64decode(r.json()["content"]).decode()
                data = json.loads(conteudo)
                print(f"[dashboard] Dados carregados do GitHub — "
                      f"saldo ${data.get('balance', 0):.2f}")
                return data, "⚠️ Dados do GitHub (PostgreSQL indisponível)"
            else:
                errors.append(f"GitHub retornou HTTP {r.status_code}")
        else:
            errors.append("GITHUB_TOKEN ou GITHUB_REPO não configurados")
    except Exception as e:
        errors.append(f"GitHub erro: {e}")

    # ── 3. ERRO explícito — sem fallback para arquivo local ───────────────────
    error_msg = " | ".join(errors)
    print(f"[dashboard] ERRO: sem fonte de dados disponível — {error_msg}")
    return None, f"ERRO: {error_msg}"
