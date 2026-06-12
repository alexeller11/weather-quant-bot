# Auditoria Técnica — Weather Trading Bot (Polymarket)

**Escopo:** 16 módulos Python lidos integralmente + dados reais embarcados (`bankroll.json`, `bankroll_override.json`).
**Entregáveis:** 15 arquivos completos corrigidos (pasta `weather-bot-corrigido/`) + segunda auditoria sobre as correções (seção final).
**Módulos sem bugs reais encontrados (não alterados):** `consensus.py`, `github_sync.py`, `config.py`, `weekly_report.py`.

A matemática das fórmulas em si (Normal, Z-score, estrutura do Kelly, PnL WIN = bruto − stake − fee) estava correta — os problemas estão nos **insumos** dessas fórmulas (timezone, unidade, fee ausente, lado do trade) e na **persistência concorrente**.

---

## CRÍTICOS

### 1. Timezone UTC em todo o pipeline meteorológico — a causa raiz da degeneração da estratégia

- **Arquivo:** `forecast.py`, `settlement.py`, `station_data.py`, `gamma_parser.py`, `bot.py`
- **Trecho:** todas as chamadas Open-Meteo com `"timezone": "UTC"`; `settlement.get_actual_temperature` (params `timezone: UTC`); `settlement._trade_is_ready` (`today_utc`); `bot._forecast_day_for_market` (`today_utc`); `gamma_parser.fetch_markets` (`datetime.now(timezone.utc)` para montar slugs D+0/D+1).
- **Problema:** `temperature_2m_max` com `timezone=UTC` agrega a máxima do **dia UTC**, mas a Polymarket resolve o mercado pela máxima do **dia local** da cidade/estação. Para a Ásia (UTC+8/+9) o recorte de dia está deslocado em até 9 horas — a "máxima do dia" comparada no settlement frequentemente pertence a outro dia.
- **Causa raiz:** confusão entre relógio do servidor (UTC) e calendário do evento (local). O efeito é assimétrico por longitude: pior na Ásia, menor na Europa, invertido nas Américas.
- **Impacto (comprovado nos dados):** os erros "impossíveis" anotados pelo próprio autor em `station_data.UNRELIABLE_CITIES` — Beijing erro médio **25.5°C**, Hong Kong **11°C** — são em grande parte artefato deste bug, não da estação. Cadeia causal completa: settlement com base errada → estatísticas de erro envenenadas → sigma inflado (4.0°C em D+0) → probabilidades EXACT colapsam (~10%) → a estratégia degenerou em apostar NO contra o bucket favorito (histórico real: 19/28 trades EXACT, 18/28 NO). Além disso `_trade_is_ready` liquidava cedo demais (Américas) ou tarde demais (Ásia), e `fetch_markets` buscava o slug do dia errado em parte do dia.
- **Criticidade:** **Crítica**
- **Correção:** `forecast.py` ganhou `CITY_TZ` (mapa IANA das 22 cidades) e `city_now()`/`city_today()` via `zoneinfo`; todas as chamadas Open-Meteo passaram para `timezone=auto` (a API devolve o dia local da coordenada); `settlement._trade_is_ready` e `bot._forecast_day_for_market` comparam contra o dia LOCAL da cidade; `gamma_parser.fetch_markets` monta D+0/D+1 com `city_today(slug)`; `station_data` filtra horas observadas em hora local.

### 2. Divergência de bankroll −$19.80 — corrupção real por escrita concorrente sem lock

- **Arquivo:** `bankroll.py` (+ `bot.py`, `settlement.py`, `notificador.py` como escritores)
- **Trecho:** padrão `load_bankroll()` → modificar → `save_bankroll()` em todos os escritores; persistência por snapshot (`INSERT` de linha nova, leitura por `ORDER BY id DESC LIMIT 1`); listener Telegram roda em **thread** dentro do worker e dispara `/settlement` como **subprocesso** `python settlement.py`; o Procfile sobe **dois containers** (worker + dashboard).
- **Problema:** três escritores concorrentes (loop principal, thread do listener, subprocesso do settlement) sem nenhum lock — nem de thread, nem de arquivo, nem no Postgres. Clássico lost update: quem salva por último apaga o que o outro fez. Adicionalmente, se o save no Postgres falha mas o arquivo local grava, o próximo `load` (que prefere o DB) faz **rollback silencioso** — trades somem do histórico e podem ser reabertos (entrada duplicada).
- **Causa raiz:** read-modify-write não atômico em estado financeiro compartilhado.
- **Impacto (comprovado nos dados):** o `bankroll.json` embarcado viola o invariante contábil. Esperado: `start − stakes_abertos + pnl_fechado = 200 − 0 + 226.3039 = 426.3039`. Gravado: `406.5040`. Diferença: **−19.7999**, que é exatamente a soma dos stakes dos 5 trades que estavam OPEN no `bankroll_override.json` (2450061_YES, 2450066_YES, 2450067_YES, 2456279_NO, 2456147_NO) — assinatura de **débito duplo de stakes** numa corrida. O override, internamente consistente em 417.4727, confirma.
- **Criticidade:** **Crítica**
- **Correção (bankroll.py reescrito):** `bankroll_lock()` reentrante (RLock de thread + `flock` com contador de profundidade — dois fds no mesmo processo deadlockariam); `atomic_update(mutator)` como única via de mutação (settlement, record_trade, reset e force_close passaram a usá-la); campo `seq` monotônico no JSON com `_load_freshest_unlocked()` escolhendo o maior seq entre DB e arquivo (anti-rollback); `pg_advisory_xact_lock` no INSERT (serializa containers distintos); escrita local atômica (`tmp` + `os.replace` + `fsync`); `record_trade` idempotente por chave única do trade; `check_balance_invariant()` para detectar corrupção (agora também exibida na warning-bar do dashboard). **Ação manual recomendada:** corrigir o saldo atual em +$19.80 (ou fazer `/resetbankroll` para re-baseline), pois a correção impede novas divergências mas não reescreve o passado.

### 3. Comandos do Telegram sem autenticação de remetente

- **Arquivo:** `notificador.py`
- **Trecho:** `iniciar_listener()` → `processar_comando(texto)` para **qualquer** update recebido; só a *resposta* ia para o `CHAT_ID`.
- **Problema:** qualquer pessoa que encontrasse o bot no Telegram podia executar `/resetbankroll` (zera saldo e histórico) e `/settlement`.
- **Causa raiz:** confusão entre "responder só para X" e "aceitar comandos só de X".
- **Impacto:** destruição remota não autenticada do estado do bot; combinado com o subprocesso do `/settlement`, também era vetor da corrupção do item 2.
- **Criticidade:** **Crítica**
- **Correção:** `_chat_autorizado()` — mensagens cujo `chat.id` ≠ `CHAT_ID` são ignoradas e logadas. `/settlement` passou a rodar **em processo** via `settle_all()` (sob o lock do bankroll), eliminando o subprocesso concorrente.

### 4. Parser perde o sinal de temperaturas negativas

- **Arquivo:** `gamma_parser.py`
- **Trecho:** regexes com `(\d+(?:\.\d+)?)` (sem `-?`); regex de range com unidade opcional no limite superior.
- **Problema (confirmado por execução):** `"-2°C or below"` → target **+2.0**; `"-4--3°C"` → exact **3.0**. E o range com unidade opcional casava intervalos de **datas** ("June 7-8" → range 7–8).
- **Causa raiz:** regex sem sinal; ambiguidade número-data não tratada.
- **Impacto:** em cidades frias, todos os mercados negativos eram avaliados com o target espelhado — probabilidade e settlement completamente errados (ex.: BELOW −2°C tratado como BELOW +2°C inverte a decisão).
- **Criticidade:** **Crítica**
- **Correção:** `_NUM = r'(-?\d+(?:\.\d+)?)'` em todos os padrões; range2 passou a **exigir** `°C/°F` após o limite superior (datas não casam mais); `hi < lo` → swap; aceita também "or above" como sinônimo de "or higher" (robustez).

---

## ALTOS

### 5. Settlement não idempotente e com fonte de dados atrasada

- **Arquivo:** `settlement.py`
- **Trecho:** `settle_trade()` notificava Telegram e atualizava calibrador/ML **por trade, antes** do `save_bankroll()` único no final; `get_actual_temperature` usava só `archive-api` (ERA5).
- **Problema:** crash/exceção entre liquidar e salvar → no ciclo seguinte os mesmos trades eram re-liquidados: crédito duplo no saldo, amostras duplicadas no calibrador, treino duplicado do ML, notificações repetidas. ERA5 tem ~5 dias de atraso de disponibilidade (e grid ≠ estação) — exatamente a janela em que trades D+0/D+1 precisam liquidar, gerando trades presos em OPEN.
- **Causa raiz:** efeitos colaterais antes da persistência; fonte única sem fallback.
- **Criticidade:** **Alta**
- **Correção:** `settle_all()` reestruturado em 4 fases: (1) descobrir prontos sem lock; (2) buscar temperaturas FORA do lock; (3) aplicar tudo numa única `atomic_update` com re-checagem de `result == "OPEN"` dentro do lock (idempotência mesmo com concorrência); (4) calibrador/ML/notificações **somente após** persistir. `get_actual_temperature` ganhou fallback `forecast-api` com `past_days=5`, com match explícito pelo `daily.time` (não índice 0 cego).

### 6. ML completamente inerte por dois bugs silenciosos

- **Arquivo:** `ml_adjuster.py`
- **Trecho:** `calibrator.calibration_data.get(city, {}).get("errors", [])`; `self._n_trades` só em memória; `compute_features` sem normalização; `update()` com hora do settlement vs `predict` com `hour=12` fixo.
- **Problema:** a estrutura real do calibrador é `[city][COND]["errors"]` — a leitura apontava um nível acima e devolvia **sempre lista vazia** (features 3–5 mortas, sem erro lançado). O contador `n_trades` zerava a cada deploy do Railway, então o gate `n >= 5` quase nunca passava: o modelo era treinado mas **praticamente nunca aplicado**. Quando aplicasse, sofreria de escala (SGD dominado por `hour_utc` 0–23) e de train/serve skew na feature de hora.
- **Causa raiz:** contrato de dados implícito entre módulos; estado em memória tratado como persistente.
- **Criticidade:** **Alta**
- **Correção:** novo helper oficial `SigmaCalibrator.get_recent_errors(city, condition=None)` consumido por `_errors_for_city()` (com fallback defensivo que percorre a estrutura aninhada corretamente); `n_trades` persistido junto do pickle no kv (`{"pkl_b64","n_trades"}`); features normalizadas para ~[0,1] e prefixo do modelo elevado para `ml_model_v3_` (não mistura pickles da escala antiga); o settlement passa a treinar com a **hora de abertura** do trade (`entry_time`), a mesma semântica usada na predição (`model.py` agora passa a hora atual).

### 7. Sigma calibrado nunca aplicado no caminho vivo

- **Arquivo:** `model.py` (+ duplicação em `forecast.py` e `risk.py`)
- **Trecho:** `calculate_probability` só consultava o calibrador quando `sigma is None or <= 0`, mas o `bot.py` **sempre** passa o sigma do forecast; e a consulta usava `condition` default "ABOVE" mesmo para EXACT/RANGE2.
- **Problema:** todo o subsistema de calibração de sigma por cidade/condição rodava, persistia, mas não influenciava nenhuma probabilidade de trade.
- **Criticidade:** **Alta**
- **Correção:** o calibrador agora recebe `condition=` quando consultado em `model.py`. O fluxo do bot continua passando o sigma do forecast (decisão do design original mantida), mas o caminho de fallback está correto e por condição; as três tabelas de sigma base permanecem como fallback local documentado.

### 8. Estatística inválida na validação e métricas com o lado do trade invertido

- **Arquivo:** `validacao.py`, `simulate.py`, `audit_model.py` (e `_calibration_bins` do `dashboard.py`)
- **Trecho:** `_confianca_binomial` com `binom.ppf(α/2, n, p_hat)/n`; Brier/edge usando `model_prob` contra `WIN` do trade independentemente do `side`.
- **Problema:** (a) o "CI" por plug-in de `p_hat` é inválido para inferência — com n=5, 5 vitórias devolvia **[100%, 100%]** e aprovava o modelo com certeza absoluta em 5 amostras; (b) `model_prob` é a prob de **YES**, mas 18/28 trades reais são NO — comparar com o WIN do trade NO inverte o sinal do erro de calibração, tornando Brier/edge agregados lixo (e inconsistentes entre módulos: o Brier do dashboard já era ciente do lado, o weekly_report também — três respostas diferentes para a mesma pergunta).
- **Criticidade:** **Alta**
- **Correção:** Wilson score interval (5/5 → [56.6%, 100%], correto); helper `prob_apostada()` (NO → 1−prob) aplicado em Brier, edge realizado, ECE, reliability diagram e bins de calibração do dashboard. Métricas agora idênticas entre validacao/simulate/audit_model/dashboard/weekly_report. Com dados reais: Brier corrigido = **0.4091** (>> 0.25), edge realizado **−41%** — o modelo estava de fato reprovado, e agora o veredito diz isso.

### 9. EXACT com bucket de ±0.5°C para mercados em °F

- **Arquivo:** `model.py` e `settlement.py`
- **Trecho:** `abs(actual − target_c) <= 0.5` e `z` com ±0.5 fixos em °C.
- **Problema:** o bucket EXACT de um mercado em °F tem largura 1°F = 0.556°C; usar ±0.5°C torna o bucket ~80% mais largo que a resolução real (0.5°F = 0.2778°C). Probabilidade superestimada na entrada e WIN/LOSS errado na borda do settlement.
- **Criticidade:** **Alta**
- **Correção:** novo `delta_to_celsius()` (conversão de largura, sem o offset −32); EXACT usa ±0.5 **na unidade do mercado** convertido; RANGE2 sem limites usa fallback ±1 na unidade; model e settlement consistentes entre si (teste 6 comprova: real a 0.467°C do target °F agora é LOSS — no código antigo seria WIN).

---

## MÉDIOS

### 10. MIN_EV nunca usado e Kelly/EV ignorando a fee de 2%

- **Arquivo:** `risk.py` (+ `bot.py` no EV gravado, `notificador.py` no bloco Kelly)
- **Problema:** `MIN_EV = 0.05` existia em `config.py` e não era lido em lugar nenhum. O Kelly usava `b = 1/price − 1`, mas o settlement desconta 2% do payout bruto — o ganho real é `b_eff = (1−fee)/price − 1`. Resultado: fração de Kelly e EV superestimados (overbetting sistemático) e trades com EV líquido negativo na margem sendo aprovados. O `ev` gravado no trade NO ainda tinha a fórmula com sinal trocado.
- **Criticidade:** **Média**
- **Correção:** `FEE_RATE = 0.02` exportado de `risk.py` (fonte única, importado pelo settlement); `_net_odds()`, `expected_value()`/`expected_value_no()`; `kelly_criterion`/`kelly_criterion_no` com `b_eff`; `check_guardrails` aplica `EV >= MIN_EV` para YES e NO; `bot.py` grava o EV líquido correto; `_kelly_math` do notificador alinhado.

### 11. Exposição podia estourar o teto e não havia limite por evento

- **Arquivo:** `risk.py` + `bot.py`
- **Trecho:** `if exposure >= MAX_TOTAL_EXPOSURE: break` **antes** de abrir o trade.
- **Problema:** com exposição 19.99 e teto 20, o próximo trade de até $4 era aprovado (23.99 efetivos). E não havia limite por evento: buckets do mesmo dia/cidade são **mutuamente exclusivos** — evidência real: 3 trades EXACT YES em Toronto 2026-06-07 (targets 23/28/29, $4 cada, a preços 0.055–0.09, todos LOSS; no máximo um poderia vencer por construção). Esses preços também estão abaixo do `MIN_PRICE=0.15` atual, indicando que o filtro foi endurecido depois do prejuízo.
- **Criticidade:** **Média**
- **Correção:** `exposure_headroom()` e o bot **clampa** o stake ao headroom (em vez de checar e estourar); `event_open_stake()`/`event_headroom()` com `MAX_EVENT_EXPOSURE` (default = `MAX_POSITION`, configurável por env) limitando o stake somado por (cidade, data); recálculo do headroom entre o lado YES e o NO do mesmo bucket.

### 12. Pseudo-replicação nas estatísticas de erro de forecast

- **Arquivo:** `sigma_calibrator.py` (e `compute_bias` em `forecast.py`)
- **Problema:** liquidar N buckets do mesmo dia/cidade registrava o **mesmo** erro de forecast N vezes — um evento meteorológico virava N observações "independentes", inflando o peso de dias com muitos trades no ajuste de sigma e no bias.
- **Criticidade:** **Média**
- **Correção:** `record_trade_result` aceita `market_date` e ignora duplicatas por (cidade, condição, dia); o settlement passa o `market_date`; `compute_bias` deduplica por (market_date, forecast_day).

### 13. Payout calculado por stake/entry_price em vez de shares

- **Arquivo:** `settlement.py`
- **Problema:** o bot arredonda `shares` para inteiro na abertura, mas o settlement recomputava `gross = stake/entry_price` — divergência de centavos versus o que a Polymarket pagaria (`shares × $1`). Ex. real: Madrid 2456279_NO.
- **Criticidade:** **Média** (erro pequeno mas sistemático e acumulativo)
- **Correção:** `gross = shares × 1.0` quando `shares` está gravado; fallback antigo mantido para trades legados sem o campo.

### 14. Dashboard: tabela de fechados nunca renderizava e saldo inicial divergente

- **Arquivo:** `dashboard.py`
- **Trecho:** `updateTables()` com `return` antecipado quando `open.length == 0`; `start = data.get("start_balance", 50)`.
- **Problema:** com 0 posições abertas (o estado real atual do bot), o `return` pulava o bloco que monta a tabela de trades fechados — ela ficava permanentemente vazia. O fallback 50 divergia do `START_BALANCE=100` do resto do sistema, distorcendo PnL% e a curva.
- **Criticidade:** **Média**
- **Correção:** blocos open/closed independentes (if/else, sem return); fallback via `config.START_BALANCE`; bins de calibração cientes do lado (item 8); **novo:** `check_balance_invariant` exposto — divergência de saldo aparece na warning-bar (o −19.80 real agora é visível); `ThreadingHTTPServer` no lugar do servidor single-thread.

### 15. Confirmação intra-dia com horas UTC tratadas como locais

- **Arquivo:** `station_data.py`
- **Problema:** cutoffs `>=18h` / `>=12h` (heurística sobre o ciclo diurno: "já é tarde, a máxima já passou") comparados com a hora **UTC**. Em Los Angeles, 18h UTC = 11h da manhã local → o filtro rejeitava entradas ABOVE válidas no meio da manhã; na Ásia, confirmava cedo demais com dados do dia errado.
- **Criticidade:** **Média**
- **Correção:** dados horários com `timezone=auto` para o dia local; `now_hour` e cutoffs em hora local via `city_now()`. Nota adicionada em `UNRELIABLE_CITIES`: os erros de Beijing/Hong Kong eram majoritariamente artefato do item 1 — manter bloqueadas até novas estatísticas pós-correção.

### 16. simulate.py: ECE por midpoint, ruína só no saldo final, backtest com parâmetros fictícios

- **Arquivo:** `simulate.py`
- **Problema:** ECE comparava o win rate do bin com o **ponto médio do bin** em vez da média das probs (com poucos trades por bin, distorce); a probabilidade de ruína do Monte Carlo só olhava o saldo **final** (um caminho que toca $0 e "se recupera" no bootstrap não é sobrevivente); `_apply_filters` hardcodava `balance=100` e cap `2.0` (o config usa 4.0) e recalculava Kelly sem fee e com o preço YES mesmo para trades NO.
- **Criticidade:** **Média**
- **Correção:** ECE e reliability diagram com média das probs do bin (e cientes do lado); ruína pelo **mínimo da trajetória**; sensitivity analysis com `START_BALANCE`/`MAX_POSITION` reais, preço do lado apostado (`entry_price`) e odds líquidas com fee; CSV de export ganhou colunas `side`/`entry_price`.

---

## BAIXOS (corrigidos junto)

- `bot.py`: `datetime.utcnow()` naive → `datetime.now(timezone.utc)` aware em `entry_time` e no relatório semanal (consistência com o resto e com `_entry_hour_utc` do settlement).
- `notificador.py`: bloco "Matemática Kelly" das notificações alinhado à fórmula com fee (era só display, mas mostrava número diferente do stake real).
- `dashboard.py`: servidor multi-thread (uma request lenta não congela mais o dashboard inteiro).
- `bankroll.py`: arredondamentos unificados em 4 casas entre abertura e settlement.

---

## Segunda auditoria (sobre as próprias correções)

Procedimento: `py_compile` dos 15 arquivos; ambiente integrado (originais não alterados + corrigidos por cima); import cruzado de todos os módulos; import completo do `bot.py` (22 cidades, sem ciclos — `gamma_parser → forecast` ok, `forecast → bankroll` só dentro de função, `notificador → settlement` lazy); testes funcionais com mocks de rede e com os **dados reais** do repositório.

**Regressão encontrada e corrigida durante a segunda auditoria:** a primeira versão de `forecast.city_today()` retornava `datetime.date` em vez de string ISO. `settlement._trade_is_ready` fazia `strptime` sobre esse valor, a exceção era engolida pelo `except` e a função retornava `False` — ou seja, **nenhum trade jamais liquidaria**. Além disso `gamma_parser` fazia aritmética `local_today + timedelta(...)` assumindo `date`. Correção: `city_today()` retorna `"YYYY-MM-DD"` (contrato documentado) e o `gamma_parser` converte localmente; todos os call-sites re-auditados e re-testados.

Resultados dos testes (todos passando):

1. **Compilação:** 15/15 OK. **Imports cruzados:** 15/15 OK, sem circularidade. `consensus`/`github_sync`/`weekly_report`/`config` importam sem alteração.
2. **Parser:** `-2°C or below` → below −2.0; `-4--3°C` → range2 [−4, −3]; `74-75°F on June 7-8` → range2 [74, 75] (a data não contamina); "or above"/"or higher" → above.
3. **Matemática:** EXACT °F com meia-largura 0.2778°C reproduz a integral da Normal com 9 casas; EXACT °C inalterado (0.09948 no caso Paris, idêntico ao valor reproduzido na auditoria do original); Kelly e EV com fee batem com o cálculo manual; Wilson 5/5 → [0.5655, 1.0] (não degenerado).
4. **Concorrência:** 50 incrementos em 5 threads via `atomic_update` → saldo exato (zero lost updates); `record_trade` duplicado → segundo rejeitado, débito único; invariante = 0.0000.
5. **Settlement:** WIN paga `shares × $1` com fee 2% (pnl 15.60 exato no caso de teste); caso na borda do bucket °F (diff 0.467°C) corretamente LOSS (era WIN no código antigo); **re-executar o settlement não credita de novo** (idempotência sob a re-checagem dentro do lock).
6. **Timezone:** dia local correto por cidade (Tóquio 12/06 20:48 enquanto LA 12/06 04:48); `_forecast_day_for_market` = 1 para o mercado de hoje local; `_trade_is_ready` False para hoje, True para ontem (no fuso da cidade).
7. **Exposição:** headroom 0.01 com exposição 19.99 (antes abriria +4.00); 3º bucket do mesmo evento Toronto bloqueado pelo `event_headroom`.
8. **Calibrador→ML:** `get_recent_errors` devolve a série correta com dedup por `market_date`; `_errors_for_city` alimenta as features (antes sempre vazio); features normalizadas conferidas.
9. **Dados reais:** `validacao`, `simulate --full`, `audit_model` e `dashboard.build_stats` rodam fim-a-fim com o `bankroll.json` do repositório; Brier unificado em 0.4091 nos quatro módulos; a divergência **−19.80 é detectada e exibida** na warning-bar do dashboard.
10. **Assinaturas/exports:** todos os símbolos consumidos entre módulos verificados presentes com assinaturas compatíveis (`calculate_probability`, `get_corrected_forecast` → 3-tupla, `get_adjusted_sigma`, `settle_all`, etc.).

**Notas operacionais para o deploy:**
- O saldo atual carrega a corrupção histórica de −$19.80. As correções impedem novas divergências, mas não reescrevem o passado: ajustar manualmente (+19.80) ou `/resetbankroll` para re-baseline.
- O prefixo do modelo ML mudou para `ml_model_v3_` de propósito: os pickles antigos foram treinados com features em escala diferente e com a leitura de erros quebrada — reaproveitá-los seria pior que recomeçar.
- As estatísticas do calibrador de sigma e o histórico de erros por cidade foram envenenados pelo bug de timezone; considerar limpar `sigma_calibration_v2` no kv_store após o deploy. Beijing/Hong Kong podem ser reavaliadas depois de ~2 semanas de dados limpos.
- `MAX_EVENT_EXPOSURE` é configurável por env (default = `MAX_POSITION`).
