"""
real_execution.py — execução de ordens reais na Polymarket.

NÃO IMPLEMENTADO.

A versão anterior deste arquivo era um stub que devolvia
`{"ok": True, "reason": "Dry Run Real OK (Aguardando Chave)"}` sem
qualquer cliente CLOB, assinatura ou ordem. O bot.py tratava esse retorno
como preenchimento real — logava "TRADE REAL EXECUTADO" e gravava o trade
no bankroll como se existisse posição. O gate para chegar aqui era apenas
`not PAPER_EXECUTION_REQUIRED and os.getenv("POLY_PRIV_KEY")`: bastava
definir POLY_PRIV_KEY para o bankroll passar a registrar trades
inexistentes.

(O stub também usava `market.get("price")`, chave que gamma_parser não
produz — é `yes_price` —, então `stake / None` levantaria TypeError. O
caminho nunca foi executado de facto.)

Para implementar, o mínimo necessário é:
  1. cliente CLOB autenticado (py-clob-client ou equivalente);
  2. token_id vindo de `clobTokenIds` (já extraído por gamma_parser);
  3. ordem marketable com limite de preço e verificação de fill;
  4. reconciliação: só gravar no bankroll o que a corretora confirmar
     preenchido, com order_id, preço médio e shares reais;
  5. tratamento de bloqueio geográfico e de ordem parcialmente
     preenchida.

Até lá, esta função levanta NotImplementedError de propósito: é melhor o
ciclo falhar de forma visível do que registrar posições fantasma.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


def execute_real_trade(market: Dict, side: str, stake: float) -> Dict:
    raise NotImplementedError(
        "Execucao real nao implementada. Rode com PAPER_EXECUTION_REQUIRED=1 "
        "(execucao simulada contra o order book real) e nao defina "
        "POLY_PRIV_KEY. Ver docstring de real_execution.py."
    )
