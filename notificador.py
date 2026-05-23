# ── IA — GROK COMO ANALISTA DO BOT (CORRIGIDO) ──────────────────────────────

def _perguntar_grok(pergunta_usuario):
    """
    Envia pergunta EXCLUSIVAMENTE para Grok (xAI).
    FIX #6: Timeout robusto e tratamento de erro.
    """
    contexto = _build_context()
    
    grok_key = os.environ.get("GROQ_API_KEY", "")
    
    if not grok_key:
        return "❌ GROQ_API_KEY não configurada!\n\nAdicione a variável de ambiente com sua chave Groq."
    
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {grok_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 600,
                "messages": [
                    {"role": "system", "content": contexto},
                    {"role": "user",   "content": pergunta_usuario},
                ],
            },
            timeout=30,  # FIX: Timeout explícito
        )
        
        if r.status_code == 200:
            data = r.json()
            return data["choices"][0]["message"]["content"]
        else:
            erro = data.get("error", {}).get("message", str(data)) if r.text else "erro desconhecido"
            return f"❌ Erro Grok {r.status_code}: {erro}"
            
    except requests.exceptions.Timeout:
        return "⏱️  Timeout — Grok demorou muito para responder. Tente novamente."
    except requests.exceptions.ConnectionError as e:
        return f"❌ Falha de conexão com Grok: {str(e)[:100]}"
    except Exception as e:
        return f"❌ Erro ao conectar com Grok: {str(e)[:200]}"
