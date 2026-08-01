# Weather Quant Bot

Bot de paper trading em mercados de temperatura da Polymarket.

> ## ⚠ Estado atual: NÃO usar capital real
>
> O histórico de 128 trades fechados (+$434 sobre $200) **não é evidência de
> edge**. Ele foi liquidado com a temperatura do Open-Meteo na coordenada do
> centro da cidade, que não é a fonte que resolve o mercado. Em Los Angeles a
> divergência medida foi de **+12,3 °F em média** (12 dias, mín. +4,0, máx.
> +18,7) contra a temperatura implícita nos preços dos buckets — e LA era 39%
> do histórico. Resultado mecânico: RANGE2/NO ganhou 26/26 e RANGE2/YES perdeu
> 0/22.
>
> Antes de qualquer conclusão sobre performance:
> 1. confirmar a estação de resolução de cada mercado e preencher
>    `station_lat`/`station_lon` em `cities.json`;
> 2. rodar `python reliquidar.py --dry-run` e depois `--apply`;
> 3. reiniciar a contagem dos 110 trades do zero.
>
> Los Angeles, Beijing e Hong Kong estão com `"active": false`.

## Arquivos principais

| Arquivo | Função |
|---|---|
| `config.py` | Fonte única de parâmetros de risco e de cidades |
| `cities.json` | Cidades, coordenadas, estação de resolução, flag `active` |
| `bankroll.py` | Persistência do saldo (PostgreSQL → local → GitHub) |
| `risk.py` | Kelly Criterion, guardrails, EV |
| `forecast.py` | Previsão via Open-Meteo + correção de bias |
| `model.py` | Probabilidades via Normal (ABOVE/BELOW/EXACT/RANGE2) |
| `gamma_parser.py` | Parser de mercados da Gamma API + filtros de liquidez |
| `bot.py` | Loop principal de trading |
| `settlement.py` | Liquidação dos trades |
| `reliquidar.py` | Reliquida o histórico contra a resolução oficial |
| `notificador.py` | Notificações Telegram + IA Groq |
| `dashboard.py` | Dashboard web |
| `consensus.py` | Motor de consenso multi-fonte |
| `sigma_calibrator.py` | Estimativa de sigma por cidade |
| `ml_adjuster.py` | Ajuste de probabilidade via SGD online (desligado) |
| `station_data.py` | Confirmação intra-dia via dados horários |
| `paper_execution.py` | Execução simulada contra o order book real |
| `real_execution.py` | Execução real — **não implementada** |
| `decision_log.py` | Telemetria de cada decisão (entrada e não-entrada) |
| `simulate.py` | Backtest e análise de performance |
| `validacao.py` | Relatório de validação do modelo |
| `github_sync.py` | Backup do bankroll no GitHub |
| `test_core.py` | Suíte de testes (123 testes) |

## Instalação

```bash
pip install -r requirements.txt
```

## Configurar .env

Copie `.env.example` e preencha. As variáveis obrigatórias são
`TELEGRAM_TOKEN`, `CHAT_ID` e `DATABASE_URL`. Sem `DATABASE_URL` o
aprendizado (sigma e ML) é perdido a cada restart do processo.

**`GITHUB_BRANCH` nunca pode ser `main`.** Um push na branch de deploy
dispara auto-deploy no Render e mata o processo no meio do ciclo. O código
recusa `main` e cai para `data-backup`, mas a variável precisa estar certa
no painel do Render.

## Ordem de execução — primeiro uso

```bash
python -m unittest test_core
```

```bash
python bot.py
```

```bash
python settlement.py
```

O primeiro comando roda a suíte de testes; o segundo sobe o bot em modo
observação (`TRADING_ENABLED=0`); o terceiro força uma liquidação manual — o
bot já liquida de hora em hora sozinho.

## Parâmetros de risco atuais (config.py)

| Parâmetro | Valor | Motivo |
|---|---|---|
| `TRADING_ENABLED` | `0` | Modo observação por segurança |
| `MIN_PROB_ABOVE_BELOW` | `0.65` | |
| `MIN_TARGET_ZSCORE` | `0.7` | |
| `MAX_BUCKET_ZDIST` | `1.0` | Compra de bucket exige previsão dentro ou perto dele |
| `MAX_POSITION` | `$4.00` | 2% de um bankroll de $200 |
| `MAX_TOTAL_EXPOSURE` | `$20.00` | 10% do bankroll |
| `MAX_OPEN_TRADES` | `5` | |
| `MIN_TRADE_STAKE` | `$1.00` | Evita posições de centavos por truncamento de shares |
| `MIN_PRICE` | `0.08` | |
| `MIN_PRICE_RANGE2` | `0.04` | Buckets raros têm preço baixo por natureza |
| `KELLY_FRACTION` | `0.50` | Half-Kelly |
| `SIGMA_MIN` / `SIGMA_MAX` | `1.0` / `8.0` | Piso de 2.0 impedia convergir para o erro real (1,72 °C) |
| `ML_BLEND_WEIGHT` | `0.0` | Blend do ML desligado — ver abaixo |
| `MIN_MARKET_LIQUIDITY` | `100` | Agora aplicado de facto |
| `MIN_MARKET_VOLUME` | `250` | Agora aplicado de facto |
| `MAX_IMPLIED_SPREAD` | `0.08` | Tolerância era de 15pp |

### Por que o ML está desligado

`ML_BLEND_WEIGHT=0`. O blend era `0.7·prob_física + 0.3·SGD`, sem trava
relativa à física. Com o SGD saturado em 1.0, qualquer mercado passava a
valer ≥ 0.30. Caso real de 2026-08-01: LA, previsão de 36,2 °C (97,2 °F),
bucket 78-79 °F, P(bucket) pela Normal = 0,0019 → `model_prob` gravado
0,3013, contra preço de 0,275, "edge" de +0,026, trade aberto. No total: 29
trades incoerentes, −$44,19; das 23 entradas em lados que o modelo dava
10–40% de chance, 23 perderam.

Há agora duas travas duras (`ML_MAX_DEVIATION`, `ML_MAX_RATIO`) que valem
mesmo se o peso for reativado. O alvo de treino também mudou: era
`trade_success` (o trade ganhou?) misturado numa saída que representa
P(mercado resolve YES) — grandezas opostas para todo trade NO. Agora é
`market_resolved_yes`.

## Formato dos mercados

| Exemplo | Tipo | Condição |
|---|---|---|
| `50°F or higher` | ABOVE | temp >= 50°F |
| `31°F or below` | BELOW | temp <= 31°F |
| `48-49°F` | RANGE2 | 48°F <= temp <= 49°F |
| `24°C` | EXACT | \|temp − 24\| <= 0,5 °C |

## Cidades

19 ativas. Inativas (`"active": false` em `cities.json`):

| Cidade | Motivo |
|---|---|
| Los Angeles | Gap de +12,3 °F entre a coordenada do bot e o mercado |
| Beijing | Erro médio histórico de 25,5 °C |
| Hong Kong | Erro médio histórico de 11 °C |

Cidade inativa não gera novas entradas mas continua liquidável — trades já
abertos precisam fechar.

### Coordenada de resolução

`station_lat` / `station_lon` em `cities.json` têm prioridade sobre
`lat`/`lon` para forecast, consenso e liquidação. Estão `null` — falta
confirmar a estação oficial de cada mercado no campo `description` do evento
na Gamma API. **Enquanto forem `null`, o bot usa o centro da cidade, que é
exatamente a causa do problema em LA.**

## Antes de usar capital real

- Estação de resolução confirmada e `station_*` preenchido para toda cidade ativa
- Histórico reliquidado (`reliquidar.py`) — a contagem reinicia do zero
- Mínimo 110 trades fechados com as regras atuais
- Win rate IC 95% inferior > 52%
- Brier out-of-sample < 0,20
- ≥ 30 trades executados contra order book real com slippage medido
- Período mínimo: 6–8 semanas

## Comandos Telegram

```
/status       — Saldo e trades abertos
/validacao    — Relatório do modelo
/settlement   — Liquidar agora
/resetbankroll [valor] — Resetar saldo (exige confirmação em 2 passos)
/help         — Ajuda
```

Só o `CHAT_ID` configurado é atendido. Qualquer outra mensagem vai para a IA
(Groq llama-3.3-70b), que analisa o bot em tempo real e responde em português.
