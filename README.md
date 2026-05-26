# Weather Quant Bot

Bot de paper trading em mercados de temperatura da Polymarket.

## Arquivos

| Arquivo | Função |
|---|---|
| `config.py` | Parâmetros de risco e configuração |
| `bankroll.py` | Persistência do saldo e histórico |
| `risk.py` | Kelly Criterion, EV, exposição |
| `forecast.py` | Previsão via Open-Meteo + bias correction |
| `model.py` | Probabilidades via distribuição Normal |
| `gamma_parser.py` | Parser de mercados da Polymarket Gamma API |
| `bot.py` | Loop principal de trading |
| `settlement.py` | Liquidação dos trades pelo resultado real |
| `notificador.py` | Notificações Telegram + IA Groq |
| `dashboard.py` | Dashboard web com globo 3D |
| `audit_model.py` | Relatório local de calibração/exposição |
| `check_version.py` | Diagnóstico rápido de guardrails |
| `emergency_flatten.py` | Zera exposição paper com VOID |
| `cleanup_history.py` | Corrige targets errados no bankroll |
| `migration.py` | Normaliza cidades + preenche EV retroativamente |

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
DATABASE_URL=postgres://...  # Railway injeta automaticamente
```

## Ordem de execução — primeiro uso

```bash
# 1. Verificar que tudo está correto
python check_version.py

# 2. Rodar o bot em modo observação (TRADING_ENABLED=0)
python bot.py

# 3. Settlement automático (o scheduler interno roda a cada hora)
# Para forçar manualmente:
python settlement.py
```

## Parâmetros de risco atuais (config.py)

| Parâmetro | Valor | Motivo |
|---|---|---|
| `TRADING_ENABLED` | `0` por padrão | Modo observação |
| `MIN_PROB_ABOVE_BELOW` | `0.70` | Dados: win rate ~0% abaixo de 0.70 |
| `MIN_TARGET_ZSCORE` | `1.50` | Targets dentro de 1.5σ são ruído |
| `MAX_POSITION` | `$2.00` | Cap por trade |
| `MAX_TOTAL_EXPOSURE` | `$8.00` | Alinhado com CHANGELOG emergency reset |
| `MAX_OPEN_TRADES` | `4` | Alinhado com CHANGELOG emergency reset |
| `KELLY_FRACTION` | `0.50` | Half-Kelly conservador |

## Cidades cobertas (22)

New York, London, Paris, Hong Kong, Tokyo, Seoul, Beijing, São Paulo,
Milan, Los Angeles, Houston, Austin, Denver, Seattle, Chicago, Phoenix,
Miami, Atlanta, Boston, Toronto, Madrid, Mexico City.

## Decisões de modelo (auditoria dos 26 trades)

**O problema central era sigma subestimado.** Com sigma de 2.0–2.6°C, o
modelo calculava probabilidades ilusoriamente precisas e entrava em trades
onde a temperatura alvo estava a menos de 1 sigma do forecast — zona de
incerteza máxima. O erro real observado foi de até 5.3°C (Denver).

**Correções aplicadas:**
- Sigma base aumentado para {1:2.8, 2:3.2, 3:3.5}°C
- MIN_PROB_ABOVE_BELOW: 0.55 → 0.70
- MIN_TARGET_ZSCORE: 0.45 → 1.50
- 3 cidades novas adicionadas (Toronto, Madrid, Mexico City)
- Slugs alternativos para NYC e outras cidades
- dashboard_server.py removido (duplicata obsoleta)

## Antes de usar capital real

- Mínimo 200 trades fechados com as regras v3
- Win rate IC 95% inferior > 52%
- Pelo menos 5 trades por cidade (para bias correction ter dados)
- Zero bugs de stake verificados
- Período mínimo: 6–8 semanas com os filtros atuais

## Auditoria e emergência

```bash
# Relatório local
python audit_model.py

# Zera exposição paper (marca OPEN como VOID)
python emergency_flatten.py

# Diagnóstico rápido
python check_version.py
```
