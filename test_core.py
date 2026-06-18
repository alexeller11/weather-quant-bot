#!/usr/bin/env python3
"""
test_core.py — Testes unitários das funções críticas

Cobre as funções financeiras mais importantes sem dependência de rede
ou banco de dados.

Execução:
    python test_core.py
    python -m pytest test_core.py -v  (se pytest instalado)
"""

import unittest
import sys
import os

# Configura ambiente minimo para importar os modulos sem DB/env real
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("TRADING_ENABLED", "0")
os.environ.setdefault("TELEGRAM_TOKEN", "")
os.environ.setdefault("CHAT_ID", "")


class TestModelProbability(unittest.TestCase):
    """Testa calculate_probability em model.py."""

    def setUp(self):
        from model import calculate_probability
        self.calc = calculate_probability

    def test_above_forecast_at_target_approx_half(self):
        """Forecast = target: P(X > target) deve ser proximo de 0.5."""
        prob = self.calc("New York", 25.0, 25.0, 1, "ABOVE", "C", sigma=4.0)
        self.assertAlmostEqual(prob, 0.5, delta=0.10)

    def test_above_forecast_well_above_target(self):
        """Forecast muito acima do target: P deve ser alta."""
        prob = self.calc("New York", 20.0, 30.0, 1, "ABOVE", "C", sigma=4.0)
        self.assertGreater(prob, 0.85)

    def test_below_forecast_well_below_target(self):
        """Forecast muito abaixo do target: P(BELOW) deve ser alta."""
        prob = self.calc("New York", 30.0, 20.0, 1, "BELOW", "C", sigma=4.0)
        self.assertGreater(prob, 0.85)

    def test_above_below_complementary(self):
        """P(ABOVE) + P(BELOW) deve ser ~1 (ignorando EXACT na fronteira)."""
        p_above = self.calc("Paris", 20.0, 24.0, 1, "ABOVE", "C", sigma=4.0)
        p_below = self.calc("Paris", 20.0, 24.0, 1, "BELOW", "C", sigma=4.0)
        self.assertAlmostEqual(p_above + p_below, 1.0, delta=0.05)

    def test_range2_at_center(self):
        """Forecast no centro do bucket: prob moderada."""
        prob = self.calc("New York", 25.0, 25.0, 1, "RANGE2", "C", sigma=4.0,
                         target_lo=24.0, target_hi=26.0)
        self.assertGreater(prob, 0.05)
        self.assertLess(prob, 0.60)

    def test_range2_forecast_far_from_bucket(self):
        """Forecast muito distante do bucket: prob deve ser baixa."""
        prob = self.calc("New York", 25.0, 5.0, 1, "RANGE2", "C", sigma=4.0,
                         target_lo=24.0, target_hi=26.0)
        self.assertLess(prob, 0.05)

    def test_fahrenheit_unit_above(self):
        """Teste ABOVE em Fahrenheit: 32F = 0C, forecast=0C -> ~0.5."""
        prob_f = self.calc("New York", 32.0, 0.0, 1, "ABOVE", "F", sigma=4.0)
        prob_c = self.calc("New York", 0.0,  0.0, 1, "ABOVE", "C", sigma=4.0)
        self.assertAlmostEqual(prob_f, prob_c, delta=0.10)

    def test_negative_temperature_below(self):
        """Caso critico: temperaturas negativas devem funcionar."""
        prob = self.calc("Toronto", -2.0, -5.0, 1, "BELOW", "C", sigma=4.0)
        self.assertGreater(prob, 0.5)  # forecast < target -> BELOW tem boa prob

    def test_negative_temperature_above(self):
        """Temperatura negativa ABOVE: forecast > target -> alta prob."""
        prob = self.calc("Toronto", -5.0, -2.0, 1, "ABOVE", "C", sigma=4.0)
        self.assertGreater(prob, 0.5)

    def test_prob_bounded(self):
        """Probabilidade sempre entre 0 e 1."""
        for sigma in [1.0, 4.0, 10.0]:
            for delta in [-20, -5, 0, 5, 20]:
                prob = self.calc("Chicago", 25.0, 25.0 + delta, 1, "ABOVE", "C", sigma=sigma)
                self.assertGreaterEqual(prob, 0.0)
                self.assertLessEqual(prob, 1.0)


class TestDeltaToCelsius(unittest.TestCase):
    """Testa a distincao critica entre delta e valor absoluto em F."""

    def test_fahrenheit_delta_not_absolute(self):
        """0.5F de LARGURA != (0.5-32)*5/9 de conversao absoluta."""
        from model import delta_to_celsius, to_celsius
        delta_c = delta_to_celsius(0.5, "F")
        self.assertAlmostEqual(delta_c, 0.5 * 5 / 9, places=5)
        # Garante que NAO usa formula absoluta (que daria negativo)
        absolute_wrong = to_celsius(0.5, "F")  # (0.5-32)*5/9 = -17.5C
        self.assertNotAlmostEqual(delta_c, absolute_wrong, places=1)

    def test_celsius_delta_identity(self):
        """Em Celsius, largura = valor (sem conversao)."""
        from model import delta_to_celsius
        self.assertEqual(delta_to_celsius(0.5, "C"), 0.5)
        self.assertEqual(delta_to_celsius(2.0, "C"), 2.0)

    def test_fahrenheit_2degree_bucket(self):
        """Bucket de 2F = 2 * 5/9 = 1.111C."""
        from model import delta_to_celsius
        result = delta_to_celsius(2.0, "F")
        self.assertAlmostEqual(result, 2.0 * 5 / 9, places=5)


class TestKellyCriterion(unittest.TestCase):
    """Testa kelly_criterion em risk.py."""

    def setUp(self):
        from risk import kelly_criterion, FEE_RATE
        self.kelly = kelly_criterion
        self.fee = FEE_RATE

    def test_zero_edge_returns_zero(self):
        """Edge zero (prob = price): Kelly = 0."""
        stake = self.kelly(prob=0.5, price=0.5, balance=100.0)
        self.assertEqual(stake, 0.0)

    def test_positive_edge_nonzero(self):
        """Edge positivo significativo: Kelly > 0."""
        stake = self.kelly(prob=0.8, price=0.5, balance=100.0)
        self.assertGreater(stake, 0.0)

    def test_fee_reduces_effective_odds(self):
        """Com fee 2%, odds efetivas sao menores que sem fee."""
        from risk import _net_odds
        b_with_fee = _net_odds(0.5)
        b_no_fee = 1.0 / 0.5 - 1.0
        self.assertLess(b_with_fee, b_no_fee)

    def test_max_position_cap(self):
        """Stake nunca excede MAX_POSITION."""
        from config import MAX_POSITION
        stake = self.kelly(prob=0.99, price=0.01, balance=10000.0)
        self.assertLessEqual(stake, MAX_POSITION)

    def test_invalid_prob_zero(self):
        self.assertEqual(self.kelly(prob=0.0, price=0.5, balance=100.0), 0.0)

    def test_invalid_prob_one(self):
        self.assertEqual(self.kelly(prob=1.0, price=0.5, balance=100.0), 0.0)

    def test_invalid_price_zero(self):
        self.assertEqual(self.kelly(prob=0.8, price=0.0, balance=100.0), 0.0)

    def test_stake_proportional_to_balance(self):
        """Stake deve ser maior com balance maior."""
        s1 = self.kelly(prob=0.8, price=0.5, balance=100.0)
        s2 = self.kelly(prob=0.8, price=0.5, balance=1000.0)
        # s2 pode ser limitado por MAX_POSITION mas nao deve ser menor que s1
        self.assertGreaterEqual(s2, s1)


class TestExpectedValue(unittest.TestCase):
    """Testa expected_value com fee."""

    def test_ev_positive_edge(self):
        """prob > price: EV deve ser positivo."""
        from risk import expected_value
        ev = expected_value(0.8, 0.5)
        self.assertGreater(ev, 0.0)

    def test_ev_zero_edge(self):
        """prob = price (ignorando fee): EV deve ser negativo (fee draga)."""
        from risk import expected_value
        ev = expected_value(0.5, 0.5)
        self.assertLess(ev, 0.0)  # fee faz EV negativo

    def test_ev_no_symmetry(self):
        """EV lado NO deve ser simetrico ao YES para prob complementar."""
        from risk import expected_value, expected_value_no
        ev_yes = expected_value(0.8, 0.3)
        ev_no  = expected_value_no(0.2, 0.7)  # prob_yes=0.2, price_yes=0.7
        self.assertAlmostEqual(ev_yes, ev_no, delta=0.01)


class TestComputeSettlement(unittest.TestCase):
    """Testa _compute_settlement em settlement.py."""

    def _trade(self, condition, target, unit="C", side="YES",
               target_lo=None, target_hi=None, stake=2.0):
        price = 0.5
        return {
            "type": condition, "target": target, "unit": unit,
            "stake": stake, "market_price": price, "entry_price": price,
            "side": side, "shares": int(stake / price),
            "result": "OPEN", "target_lo": target_lo, "target_hi": target_hi,
        }

    def test_above_win(self):
        from settlement import _compute_settlement
        r = _compute_settlement(self._trade("ABOVE", 25.0), 27.0)
        self.assertEqual(r["result"], "WIN")
        self.assertGreater(r["pnl"], 0)

    def test_above_loss(self):
        from settlement import _compute_settlement
        r = _compute_settlement(self._trade("ABOVE", 25.0), 23.0)
        self.assertEqual(r["result"], "LOSS")
        self.assertLess(r["pnl"], 0)

    def test_below_win(self):
        from settlement import _compute_settlement
        r = _compute_settlement(self._trade("BELOW", 25.0), 23.0)
        self.assertEqual(r["result"], "WIN")

    def test_below_loss(self):
        from settlement import _compute_settlement
        r = _compute_settlement(self._trade("BELOW", 25.0), 27.0)
        self.assertEqual(r["result"], "LOSS")

    def test_above_boundary_inclusive(self):
        """Polymarket 'or higher' inclui o alvo."""
        from settlement import _compute_settlement
        r = _compute_settlement(self._trade("ABOVE", 25.0), 25.0)
        self.assertEqual(r["result"], "WIN")

    def test_below_boundary_inclusive(self):
        """Polymarket 'or below' inclui o alvo."""
        from settlement import _compute_settlement
        r = _compute_settlement(self._trade("BELOW", 25.0), 25.0)
        self.assertEqual(r["result"], "WIN")

    def test_range2_win_inside(self):
        from settlement import _compute_settlement
        r = _compute_settlement(
            self._trade("RANGE2", 25.0, target_lo=24.0, target_hi=26.0), 25.0
        )
        self.assertEqual(r["result"], "WIN")

    def test_range2_loss_outside(self):
        from settlement import _compute_settlement
        r = _compute_settlement(
            self._trade("RANGE2", 25.0, target_lo=24.0, target_hi=26.0), 28.0
        )
        self.assertEqual(r["result"], "LOSS")

    def test_negative_temp_below(self):
        """Caso critico: BELOW -2C com real=-3C deve ser WIN."""
        from settlement import _compute_settlement
        r = _compute_settlement(self._trade("BELOW", -2.0), -3.0)
        self.assertEqual(r["result"], "WIN")

    def test_negative_temp_above(self):
        """ABOVE -5C com real=-2C deve ser WIN."""
        from settlement import _compute_settlement
        r = _compute_settlement(self._trade("ABOVE", -5.0), -2.0)
        self.assertEqual(r["result"], "WIN")

    def test_no_side_inverts_above(self):
        """Lado NO inverte o resultado: YES ganha -> NO perde."""
        from settlement import _compute_settlement
        trade = self._trade("ABOVE", 25.0, side="NO")
        trade["entry_price"] = 0.5
        r = _compute_settlement(trade, 27.0)  # YES ganharia
        self.assertEqual(r["result"], "LOSS")  # NO perde

    def test_fee_applied_on_win(self):
        """Fee deve ser descontada do payout na vitoria."""
        from settlement import _compute_settlement
        from risk import FEE_RATE
        r = _compute_settlement(self._trade("ABOVE", 25.0, stake=2.0), 27.0)
        self.assertGreater(r["fee"], 0)
        shares = r.get("shares", 4)  # 2.0 / 0.5 = 4
        gross = shares * 1.0
        expected_fee = round(gross * FEE_RATE, 4)
        self.assertAlmostEqual(r["fee"], expected_fee, places=3)

    def test_no_fee_on_loss(self):
        """Fee deve ser zero na derrota."""
        from settlement import _compute_settlement
        r = _compute_settlement(self._trade("ABOVE", 25.0), 23.0)
        self.assertEqual(r["fee"], 0.0)


class TestParseQuestion(unittest.TestCase):
    """Testa parse_question em gamma_parser.py."""

    def setUp(self):
        from gamma_parser import parse_question
        self.parse = parse_question

    def test_above_fahrenheit(self):
        r = self.parse("Will the highest temperature be 50\u00b0F or higher?")
        self.assertEqual(r["condition"], "above")
        self.assertEqual(r["target"], 50.0)
        self.assertEqual(r["unit"], "F")

    def test_below_fahrenheit(self):
        r = self.parse("31\u00b0F or below")
        self.assertEqual(r["condition"], "below")
        self.assertEqual(r["target"], 31.0)

    def test_negative_below_celsius(self):
        """Caso critico: temperatura negativa sem sinal perdido."""
        r = self.parse("-2\u00b0C or below")
        self.assertIsNotNone(r)
        self.assertEqual(r["condition"], "below")
        self.assertEqual(r["target"], -2.0)
        self.assertEqual(r["unit"], "C")

    def test_negative_above_celsius(self):
        r = self.parse("-5\u00b0C or higher")
        self.assertIsNotNone(r)
        self.assertEqual(r["condition"], "above")
        self.assertEqual(r["target"], -5.0)

    def test_range2_fahrenheit(self):
        r = self.parse("48-49\u00b0F")
        self.assertEqual(r["condition"], "range2")
        self.assertAlmostEqual(r["target_lo"], 48.0)
        self.assertAlmostEqual(r["target_hi"], 49.0)
        self.assertEqual(r["unit"], "F")

    def test_range2_celsius(self):
        r = self.parse("24-25\u00b0C")
        self.assertEqual(r["condition"], "range2")
        self.assertEqual(r["unit"], "C")

    def test_unknown_format_returns_none(self):
        r = self.parse("invalid format xyz")
        self.assertIsNone(r)


class TestRiskCircuitBreakers(unittest.TestCase):
    def test_daily_loss_blocks_new_entries(self):
        from datetime import datetime, timezone
        from config import MAX_DAILY_LOSS
        from risk import risk_limits_ok
        history = [{
            "result": "LOSS",
            "pnl": -(MAX_DAILY_LOSS + 1),
            "exit_time": datetime.now(timezone.utc).isoformat(),
        }]
        ok, reason = risk_limits_ok(history, balance=100.0, start_balance=100.0)
        self.assertFalse(ok)
        self.assertIn("diario", reason)

    def test_positive_balance_without_losses_allows_entries(self):
        from risk import risk_limits_ok
        ok, reason = risk_limits_ok([], balance=100.0, start_balance=100.0)
        self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
