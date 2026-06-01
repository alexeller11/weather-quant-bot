# Weather Quant Bot v5

Bot de paper trading em mercados de temperatura da Polymarket.

## Arquivos principais

| Arquivo | Função |
|---|---|
| `config.py` | Parâmetros de risco e configuração |
| `bankroll.py` | Persistência do saldo (PostgreSQL → local → GitHub) |
| `risk.py` | Kelly Criterion, guardrails, EV |
| `forecast.py` | Previsão via Open-Meteo + bias correction |
| `model.py` | Probabilidades via distribuição Normal (ABOVE/BELOW/RANGE2) |
| `gamma_parser.py` | Parser de mercados da Polymarket Gamma API |
| `bot.py` | Loop principal de trading |
| `settlement.py` | Liquidação dos trades pelo resultado real |
| `notificador.py` | Notificações Telegram + IA Groq |
| `dashboard.py` | Dashboard web com globo 3D |
| `audit_model.py` | Relatório local de calibração/exposição |
| `check_version.py` | Diagnóstico rápido v5 |
| `consensus.py` | Motor de consenso multi-fonte |
| `sigma_calibrator.py` | Calibração de sigma por cidade |
| `ml_adjuster.py` | Ajuste de probabilidade via SGD online |
| `station_data.py` | Confirmação intra-dia via dados horários |
| `simulate.py` | Backtest e análise de performance |
| `validacao.py` | Relatório de validação do modelo |
| `github_sync.py` | Backup do bankroll no GitHub |

## Instalação

```bash
pip install -r requirements.txt
```

## Configurar .env

```
TELEGRAM_TOKEN=seu_token_aqui
CHAT_ID=seu_chat_id_aqui
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
GITHUB_REPO=seu_usuario/weather-quant-bot
GITHUB_BRANCH=main
GROQ_API_KEY=sua_chave_groq
WEATHERAPI_KEY=sua_chave_weatherapi   # opcional
DATABASE_URL=postgres://...           # Railway injeta automaticamente
TRADING_ENABLED=0                     # 0=observação, 1=trading
```

## Ordem de execução — primeiro uso

```bash
# 1. Verificar que tudo está correto
python check_version.py

# 2. Rodar o bot em modo observação (TRADING_ENABLED=0)
python bot.py

# 3. Settlement automático (scheduler interno roda a cada hora)
# Para forçar manualmente:
python settlement.py
```

## Parâmetros de risco atuais (config.py)

| Parâmetro | Valor | Motivo |
|---|---|---|
| `TRADING_ENABLED` | `0` | Modo observação por segurança |
| `MIN_PROB_ABOVE_BELOW` | `0.80` | Calibrado com dados reais |
| `MIN_TARGET_ZSCORE` | `1.00` | Alinhado com sigma=4.0 |
| `MAX_POSITION` | `$4.00` | 2% do bankroll de $200 |
| `MAX_TOTAL_EXPOSURE` | `$20.00` | 10% do bankroll |
| `MAX_OPEN_TRADES` | `5` | Diversificação adequada |
| `MIN_PRICE` | `0.10` | Aceita buckets de 2°F |
| `KELLY_FRACTION` | `0.50` | Half-Kelly conservador |

## Formato dos mercados (v5)

A Polymarket usa buckets de 2°F/°C. O bot reconhece três tipos:

| Exemplo | Tipo | Condição |
|---|---|---|
| `50°F or higher` | ABOVE | temp >= 50°F |
| `31°F or below` | BELOW | temp <= 31°F |
| `48-49°F` | RANGE2 | 48°F <= temp <= 49°F |

## Cidades cobertas (20 ativas)

New York, London, Paris, Tokyo, Seoul, São Paulo, Milan,
Los Angeles, Houston, Austin, Denver, Seattle, Chicago, Phoenix,
Miami, Atlanta, Boston, Toronto, Madrid, Mexico City.

Beijing e Hong Kong bloqueadas por erro sistemático de forecast > 5°C.

## Antes de usar capital real

- Mínimo 200 trades fechados com as regras v5
- Win rate IC 95% inferior > 52%
- Pelo menos 10 trades RANGE2 para calibrar sigma
- Período mínimo: 6–8 semanas

## Comandos Telegram

```
/status       — Saldo e trades abertos
/validacao    — Relatório do modelo
/settlement   — Liquidar agora
/resetbankroll [valor] — Resetar saldo
/help         — Ajuda
```

Qualquer outra mensagem é enviada para a IA (Groq llama-3.3-70b)
que analisa o bot em tempo real e responde em português.
