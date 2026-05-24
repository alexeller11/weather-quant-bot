# Weather Quant Bot — Changelog de Correções

## Arquivos modificados

## 2026-05-24 — Emergency model/risk reset

### `bankroll.json`
- 17 trades `OPEN` foram marcados como `VOID`
- Exposição paper removida: `$41.90`
- Saldo recalculado por histórico fechado: `$33.69`

### `model.py` / `forecast.py`
- Removida a dupla contagem de sigma
- `CITY_SIGMA_CLIMO` agora atua como piso, não como erro independente somado em quadratura
- Adicionado teto de sigma para bloquear probabilidades artificiais

### `bot.py` / `config.py`
- Bot fica em modo observação por padrão (`TRADING_ENABLED=0`)
- Zona neutra `0.45 <= model_prob <= 0.55` bloqueada
- Bloqueio por target perto demais do forecast (`MIN_TARGET_ZSCORE`)
- Risco reduzido: cap por trade `$2`, exposição máxima `$8`, no máximo 4 abertos
- EV extremo bloqueado para evitar preço stale/ilíquido

### Novos utilitários
- `audit_model.py`: relatório local de calibração/exposição
- `emergency_flatten.py`: zera exposição paper com `VOID`

---

### `notificador.py` (era `telegram.py`)
**Por que renomear?**
O Python tem um pacote pip chamado `python-telegram-bot` que instala um módulo
também chamado `telegram`. Quando bot.py fazia `from telegram import ...`, o Python
podia importar o pacote pip em vez do seu arquivo local — silenciosamente, sem erro,
e substituindo todas as funções por no-ops.

**Mudanças:**
- Renomeado para `notificador.py` — sem colisão de nome possível
- Tokens lidos de `config.py` / `.env` — nunca hardcoded no código
- `enviar_mensagem` agora loga o erro em vez de engolir com bare `except`

---

### `bot.py`
**Bug crítico corrigido — `calculate_probability` com args errados:**
```python
# ANTES (errado) — target=0, unit="C", condition="above" (defaults)
model_prob = calculate_probability(
    city=city,
    market_date=market.get("market_date", ""),   # kwarg inexistente
    question=market.get("question", ""),          # kwarg inexistente
)
# Calculava P(temp > 0°C) ≈ sempre 100% → edge completamente falso

# DEPOIS (correto)
model_prob = calculate_probability(
    city=city,
    target=target,
    unit=unit,
    forecast_day=forecast_day,
    condition=condition.lower(),
)
```

**Dimensionamento de posição corrigido:**
```python
# ANTES: USD → shares (erro de arredondamento em preços baixos)
stake = round(kelly_stake(...), 2)

# DEPOIS: shares inteiros → USD real
shares    = int(stake / market_price)
real_cost = round(shares * market_price, 2)
stake     = real_cost
```

**Import corrigido:**
```python
# ANTES (silenciosamente falso):
try:
    from telegram import notificar_entrada_trade
except:
    def notificar_entrada_trade(*args, **kwargs): pass

# DEPOIS (falha explícita se houver problema):
from notificador import notificar_entrada_trade
```

---

### `settlement.py`
**Notificações Telegram adicionadas:**
- `notificar_settlement_win()` chamado a cada WIN
- `notificar_settlement_loss()` chamado a cada LOSS  
- `notificar_settlement_resumo()` chamado ao final se houve resoluções

Antes, o settlement rodava completamente silencioso — nenhuma mensagem chegava
no Telegram independente do resultado.

---

### `config.py`
Houston adicionado em `CITY_SLUGS`, `CITY_COORDS_BY_SLUG`, `CITY_DISPLAY`
e `CITY_SLUG_NORMALIZE`. A cidade aparecia em trades do bankroll mas não tinha
coordenadas definidas, o que fazia `get_real_temperature` retornar `None`.

---

## Arquivos não modificados
- `bankroll.py` — sem alterações
- `model.py` — sem alterações
- `risk.py` — sem alterações
- `gamma_parser.py` — sem alterações

---

## Passos para deploy

1. Substitua todos os arquivos `.py` na pasta `C:\weather-trading-bot\`
2. **NÃO** copie o `telegram.py` antigo — ele foi substituído por `notificador.py`
3. Confirme que o `.env` tem as duas linhas:
   ```
   TELEGRAM_TOKEN=seu_token_aqui
   CHAT_ID=seu_chat_id_aqui
   ```
4. Teste o Telegram: `python notificador.py`
5. Rode o bot: `python bot.py`
