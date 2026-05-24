# Weather Quant Bot

Sistema de paper trading em mercados de temperatura da Polymarket.

## Arquivos

| Arquivo | Função |
|---|---|
| `config.py` | Parâmetros de risco e configuração |
| `bankroll.py` | Persistência do saldo e histórico |
| `risk.py` | Kelly Criterion, EV, exposição |
| `model.py` | Previsão via Open-Meteo (ensemble + fallback) |
| `gamma_parser.py` | Parser de mercados da Polymarket Gamma API |
| `bot.py` | Loop principal de trading |
| `settlement.py` | Liquidação dos trades pelo resultado real |
| `telegram.py` | Notificações |
| `migration.py` | Migração e normalização do bankroll.json |
| `reset_bankroll.py` | Reset completo do histórico |

## Instalação

```bash
pip install -r requirements.txt
```

## Configurar .env

```
TELEGRAM_TOKEN=seu_token_aqui
CHAT_ID=seu_chat_id_aqui
```

## Ordem de execução — primeiro uso

```bash
# 1. (Opcional) Migrar bankroll.json existente
python migration.py

# 2. (Opcional) Resetar para começar do zero
python reset_bankroll.py

# 3. Rodar o bot
python bot.py

# 4. Rodar settlement uma vez por dia (após meia-noite UTC)
python settlement.py
```

## Parâmetros de risco (config.py)

| Parâmetro | Valor | Descrição |
|---|---|---|
| `TRADING_ENABLED` | `0` por padrão | Modo observação; use `1` para permitir novas entradas |
| `EDGE_THRESHOLD` | 0.12 | Edge mínimo (model_prob - market_price) |
| `MAX_POSITION` | 2.0 | Cap em dólares por trade |
| `MAX_TOTAL_EXPOSURE` | 8.0 | Exposição total máxima em dólares |
| `MAX_OPEN_TRADES` | 4 | Máximo de trades abertos |
| `MAX_TRADES_PER_CYCLE` | 2 | Máximo de novas entradas por ciclo |
| `KELLY_FRACTION` | 0.5 | Multiplicador do Kelly (half-Kelly) |
| `POLYMARKET_FEE` | 0.02 | Taxa sobre o lucro (2%) |

## Auditoria e emergência

```bash
# Relatório local de calibração, PnL, exposição e flags de risco
python audit_model.py

# Zera exposição paper: marca OPEN como VOID e recalcula saldo
python emergency_flatten.py
```

Após uma intervenção de modelo, o bot fica pausado por padrão. Reative apenas
quando o relatório estiver aceitável:

```bash
TRADING_ENABLED=1 python bot.py
```

## Antes de usar capital real

- Mínimo 200 trades fechados em paper trading
- Win rate IC 95% inferior > 55%
- Edge distribuído por todas as 5 cidades
- Zero bugs de stake (verificar MAX_POSITION sendo respeitado)
- Período mínimo: 6–8 semanas de testes

## Correções implementadas (v2)

- Regex de detecção F/°F robusta + sanity check target > 55°C
- Bug de MAX_POSITION: bankroll recarregado a cada cidade
- Sanity check final de stake antes de registrar trade
- normalize_city() — elimina "Los-Angeles" vs "Los Angeles"
- Ensemble Open-Meteo para sigma real (fallback para hardcoded)
- migration.py: normaliza cidades + preenche EV retroativamente
- reset_bankroll.py: reset seguro com backup automático
