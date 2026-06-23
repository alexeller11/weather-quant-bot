# Weather Quant Bot — Changelog de Correções

## 2026-06-23 — Hardening v2 (branch feature/correcoes-auditoria-v2)

### P1-1: RANGE2/EXACT zscore — distância à borda mais próxima (bug crítico)
- **Antes**: RANGE2 e EXACT usavam `|forecast - target_midpoint|` para o zscore,
  superestimando a proximidade quando o forecast estava perto da borda do bucket.
  Conservativo (bloqueava trades válidos), mas inconsistente com ABOVE/BELOW.
- **Depois**: Novo helper `_nearest_edge_distance()` calcula a distância em °C
  à borda mais próxima do bucket para TODAS as condições:
  - ABOVE/BELOW → distância ao target (inalterado)
  - RANGE2 → `min(|forecast - lo|, |forecast - hi|)`
  - EXACT → `min(|forecast - (target ± 0.5 unidade)|)`
- `check_guardrails()` e `_check_no_guardrails()` unificados — ambos chamam
  `_nearest_edge_distance()` no zscore check.
- `bot.py`: `market_dict` agora inclui `target_lo` e `target_hi`.

### P1-2: Cooldown após consecutive losses
- Novo `trading_cooldown(history)` em `risk.py`:
  - 3 losses seguidos → pausa de 4h (configurável via `COOLDOWN_3LOSSES_H`)
  - 5 losses seguidos → pausa de 12h (configurável via `COOLDOWN_5LOSSES_H`)
  - Settlement continua permitido (reduz exposição durante streaks)
- Integrado em `bot.py:scheduled_trading()` antes do loop de cidades.

### P1-3: Zscore check para RANGE2/EXACT no lado NO
- `_check_no_guardrails()` agora usa `_nearest_edge_distance()` em vez de
  `|forecast - target_c|`, consistente com o lado YES.

### P2-1: Sigma shrinkage para cidades com poucas amostras
- `SigmaCalibrator.get_adjusted_sigma()` agora aplica shrinkage bayesiano:
  - `n < 5` → adjustment = 0 (amostras insuficientes)
  - `5 ≤ n < 20` → `adjustment × (n - 5) / 15` (rampa linear)
  - `n ≥ 20` → adjustment completo
- Evita que cidades com 1-2 observações dominem o sigma com ajustes ruidosos.

### P2-2: settlement.py — lookup de cidade por slug/display/aliases
- `_get_city_coordinates()` agora busca por `slug`, `display` e `aliases`
  (case-insensitive) em vez de `city["name"]` (chave que não existe no
  `cities.json` atual).
- Fallback compat: se o JSON tiver a chave `name` legada, ainda funciona.

### Bug extra: `return False` duplicado em `_check_no_guardrails`
- Linha duplicada após o zscore check NO removida — unreachable code.

### Validação
- `test_core.py`: **69/69** testes passando (27 novos)
  - `TestNearestEdgeDistance` (8 testes) — acima/abaixo, RANGE2, EXACT, °F
  - `TestTradingCooldown` (6 testes) — 3 losses, 5 losses, expirado, WIN quebra, vazio
  - `TestSigmaShrinkage` (4 testes) — n<5, rampa, n≥20, sem dados
  - `TestSettlementCityLookup` (4 testes) — slug, display, alias, desconhecida
  - +5 testes anteriores existentes
- `py_compile`: todos os `.py` modificados compilam sem erro

---

## 2026-06-22 — Auditoria completa (branch feature/correcoes-auditoria)

### Correções de segurança
- **#1** `git rm --cached bankroll.json` — saldo e histórico vazavam no repositório público

### Remoção de código morto
- **#4** Deletados scripts órfãos e arquivos mortos: `corrigir_bankroll.py`, `fix_db.py`, `patch_dashboard.py`, `dashboard.py.bak`, `bankroll.json.bak`, `env.example`, `gitignore`, `arquivos.txt`

### Correções de dados
- **#2** Trade duplicado de Seattle removido do bankroll, saldo ajustado −$0.42

### Correções de lógica
- **#3** Precedência de ternário em `weekly_report.py` — f-string com ternário não-entre-parentheses causava resultado errado
- **risk.py v5.5** — `MIN_PRICE_YES_FOR_NO` env var, suporte a lado NO em RANGE2
- **consensus.py v2.1** — thresholds EXACT 2.5°C, RANGE2 3.5°C
- **NOTA (bug conhecido, não corrigido)**: RANGE2 zscore usa `target` (midpoint do bucket) em vez de `target_lo`, tornando o zscore conservativo (superestima proximidade). Decisão: correção segura mas adiada; o bot não está pronto para capital real (Brier 0.2192, edge realizado −17.6%).

### Padronização print() → logger
- **#7** Todos os `print()` em módulos de produção convertidos para `logging`:
  - `github_sync.py` (14 prints)
  - `gamma_parser.py` (10 prints)
  - `forecast.py` (14 prints)
  - `bankroll.py` (6 prints, incluindo 2 multiline)
  - `notificador.py` (7 prints; 2 prints do bloco `__main__` CLI preservados)

### Unificação de cidades em `cities.json`
- **#6** Criado `cities.json` — **fonte única de verdade** para as 22 cidades:
  - Cada entrada: `slug`, `display`, `lat`, `lon`, `tz`, `aliases`
- `config.py`: `build_city_maps()` deriva `CITY_DISPLAY`, `CITY_SLUG_NORMALIZE`, `CITY_SLUGS`, `CITY_COORDS`, `CITY_TZ`, `CITY_SLUG_ALIASES` a partir do JSON
- `forecast.py`: `CITY_COORDS` e `CITY_TZ` removidos (importados de `config`)
- `gamma_parser.py`: `CITY_SLUG_ALIASES` removido (importado de `config`)
- `station_data.py`: import de `CITY_COORDS` movido de `forecast` para `config`
- **Bug indireto corrigido**: `CITY_SLUG_NORMALIZE` agora mapeia para slugs com hífen (consistente com `normalize_city_slug()`), não mais para formato com espaço

### Validação
- `test_core.py`: **42/42** testes passando
- `py_compile`: todos os `.py` compilam sem erro
- Sanity check: 22 slugs, 22 coords, 22 timezones, 34 entradas de normalize — todas consistentes

---

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

## Arquivos não modificados (em 2026-05-24)
- `bankroll.py` — sem alterações na época
- `model.py` — sem alterações na época
- `risk.py` — sem alterações na época
- `gamma_parser.py` — sem alterações na época

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
