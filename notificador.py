def _perguntar_grok(pergunta_usuario):
    """
    Envia pergunta EXCLUSIVAMENTE para Grok (xAI).
    """
    contexto = _build_context()

    # Procura primeiro GROK_API_KEY
    # Se não existir, tenta GROQ_API_KEY
    grok_key = (
        os.environ.get("GROK_API_KEY")
        or os.environ.get("GROQ_API_KEY")
        or ""
    )

    if not grok_key:
        return (
            "❌ Nenhuma chave configurada!\n\n"
            "Adicione GROK_API_KEY no Railway."
        )

    try:
        r = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {grok_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-2",
                "max_tokens": 600,
                "messages": [
                    {
                        "role": "system",
                        "content": contexto
                    },
                    {
                        "role": "user",
                        "content": pergunta_usuario
                    },
                ],
            },
            timeout=30,
        )

        data = r.json()

        if r.status_code == 200:
            return data["choices"][0]["message"]["content"]

        else:
            erro = data.get("error", {}).get("message", str(data))
            return f"❌ Erro Grok {r.status_code}: {erro}"

    except requests.exceptions.Timeout:
        return (
            "⏱️ Timeout — Grok demorou muito "
            "para responder."
        )

    except Exception as e:
        return f"❌ Erro ao conectar com Grok: {str(e)}"
