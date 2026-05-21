def _perguntar_grok(pergunta_usuario):

    contexto = _build_context()

    grok_key = (
        os.environ.get("GROK_API_KEY")
        or os.environ.get("GROQ_API_KEY")
        or ""
    )

    if not grok_key:

        return (
            "❌ GROK_API_KEY não configurada."
        )

    try:

        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {grok_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-beta",
                "messages": [
                    {
                        "role": "system",
                        "content": contexto
                    },
                    {
                        "role": "user",
                        "content": pergunta_usuario
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 600
            },
            timeout=30
        )

        print("\n===== GROK DEBUG =====")
        print("STATUS:", r.status_code)
        print("TEXT:", r.text[:1000])
        print("======================\n")

        try:

            data = r.json()

        except Exception:

            return (
                "❌ Resposta inválida da API:\n\n"
                f"{r.text[:300]}"
            )

        if r.status_code == 200:

            if (
                isinstance(data, dict)
                and "choices" in data
            ):

                return (
                    data["choices"][0]
                    ["message"]["content"]
                )

            return (
                "❌ Resposta inesperada:\n\n"
                f"{str(data)[:500]}"
            )

        erro = ""

        if isinstance(data, dict):

            erro = (
                data.get("error", "")
            )

        if not erro:

            erro = str(data)

        return (
            f"❌ Erro API {r.status_code}\n\n"
            f"{erro}"
        )

    except requests.exceptions.Timeout:

        return (
            "⏱️ Timeout da API Grok."
        )

    except Exception as e:

        return (
            f"❌ Erro ao conectar:\n\n"
            f"{str(e)}"
        )
