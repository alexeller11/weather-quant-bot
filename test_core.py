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
import tempfile

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
        stake = self.kelly(model_prob=0.5, price=0.5, balance=100.0)
        self.assertEqual(stake, 0.0)

    def test_positive_edge_nonzero(self):
        """Edge positivo significativo: Kelly > 0."""
        stake = self.kelly(model_prob=0.8, price=0.5, balance=100.0)
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
        stake = self.kelly(model_prob=0.99, price=0.01, balance=10000.0)
        self.assertLessEqual(stake, MAX_POSITION)

    def test_invalid_prob_zero(self):
        self.assertEqual(self.kelly(model_prob=0.0, price=0.5, balance=100.0), 0.0)

    def test_invalid_prob_one(self):
        self.assertEqual(self.kelly(model_prob=1.0, price=0.5, balance=100.0), 0.0)

    def test_invalid_price_zero(self):
        self.assertEqual(self.kelly(model_prob=0.8, price=0.0, balance=100.0), 0.0)

    def test_stake_proportional_to_balance(self):
        """Stake deve ser maior com balance maior."""
        s1 = self.kelly(model_prob=0.8, price=0.5, balance=100.0)
        s2 = self.kelly(model_prob=0.8, price=0.5, balance=1000.0)
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


class TestNearestEdgeDistance(unittest.TestCase):
    """Testa _nearest_edge_distance em risk.py — distância à borda mais próxima."""

    def setUp(self):
        from risk import _nearest_edge_distance
        self.ned = _nearest_edge_distance

    def test_above_returns_distance_to_target(self):
        """ABOVE: distância absoluta ao target."""
        dist = self.ned(30.0, "ABOVE", 25.0, "C")
        self.assertAlmostEqual(dist, 5.0)

    def test_below_returns_distance_to_target(self):
        """BELOW: distância absoluta ao target."""
        dist = self.ned(20.0, "BELOW", 25.0, "C")
        self.assertAlmostEqual(dist, 5.0)

    def test_range2_inside_bucket_near_lo(self):
        """RANGE2: forecast dentro do bucket — mais perto da borda lo."""
        dist = self.ned(24.5, "RANGE2", 25.0, "C", target_lo_raw=24.0, target_hi_raw=26.0)
        self.assertAlmostEqual(dist, 0.5)  # 24.5 - 24.0

    def test_range2_inside_bucket_near_hi(self):
        """RANGE2: forecast dentro do bucket — mais perto da borda hi."""
        dist = self.ned(25.5, "RANGE2", 25.0, "C", target_lo_raw=24.0, target_hi_raw=26.0)
        self.assertAlmostEqual(dist, 0.5)  # 26.0 - 25.5

    def test_range2_outside_bucket_below(self):
        """RANGE2: forecast fora do bucket, abaixo."""
        dist = self.ned(22.0, "RANGE2", 25.0, "C", target_lo_raw=24.0, target_hi_raw=26.0)
        self.assertAlmostEqual(dist, 2.0)  # 24.0 - 22.0

    def test_range2_outside_bucket_above(self):
        """RANGE2: forecast fora do bucket, acima."""
        dist = self.ned(28.0, "RANGE2", 25.0, "C", target_lo_raw=24.0, target_hi_raw=26.0)
        self.assertAlmostEqual(dist, 2.0)  # 28.0 - 26.0

    def test_range2_fahrenheit_converts_edges(self):
        """RANGE2 em °F: bordas convertidas para °C antes da distância."""
        # bucket 48-49°F → 8.89–9.44°C; forecast 47°F → 8.33°C
        # distância = 8.89 - 8.33 ≈ 0.556°C
        # forecast_temp já em °C (caller converte antes de chamar)
        forecast_c = (47.0 - 32) * 5 / 9      # 8.333
        target_c = (48.5 - 32) * 5 / 9        # 9.167 (midpoint já em °C)
        dist = self.ned(forecast_c, "RANGE2", target_c, "F",
                        target_lo_raw=48.0, target_hi_raw=49.0)
        expected_lo_c = (48.0 - 32) * 5 / 9   # 8.889
        self.assertAlmostEqual(dist, abs(expected_lo_c - forecast_c), places=3)

    def test_exact_near_edge(self):
        """EXACT: distância à borda target-0.5."""
        dist = self.ned(24.6, "EXACT", 25.0, "C")
        self.assertAlmostEqual(dist, 0.1)  # 24.6 - (25.0 - 0.5) = 24.6 - 24.5

    def test_exact_outside_above(self):
        """EXACT: forecast fora acima do bucket."""
        dist = self.ned(26.2, "EXACT", 25.0, "C")
        self.assertAlmostEqual(dist, 0.7)  # 26.2 - 25.5


class TestTradingCooldown(unittest.TestCase):
    """Testa trading_cooldown em risk.py."""

    def _make_history(self, n_losses, last_exit_minutes_ago=60):
        """Gera history com n consecutive losses, último há last_exit_minutes_ago."""
        from datetime import datetime, timezone, timedelta
        history = []
        last_time = datetime.now(timezone.utc) - timedelta(minutes=last_exit_minutes_ago)
        for i in range(n_losses):
            history.append({
                "result": "LOSS",
                "exit_time": (last_time + timedelta(minutes=i)).isoformat(),
            })
        return history

    def test_no_cooldown_under_3_losses(self):
        from risk import trading_cooldown
        active, reason = trading_cooldown(self._make_history(2, 30))
        self.assertFalse(active)

    def test_cooldown_active_after_3_losses(self):
        from risk import trading_cooldown
        active, reason = trading_cooldown(self._make_history(3, 10))
        self.assertTrue(active)
        self.assertIn("3", reason)

    def test_cooldown_expired_after_4h(self):
        """3 losses há mais de 4h: cooldown expirou."""
        from risk import trading_cooldown
        active, reason = trading_cooldown(self._make_history(3, 250))  # >4h
        self.assertFalse(active)

    def test_cooldown_5_losses_longer(self):
        """5 losses: cooldown de 12h."""
        from risk import trading_cooldown
        active, reason = trading_cooldown(self._make_history(5, 10))
        self.assertTrue(active)
        self.assertIn("5", reason)

    def test_wins_break_consecutive_count(self):
        """Um WIN recente zera o contador de losses consecutivos."""
        from risk import trading_cooldown
        from datetime import datetime, timezone
        # Cria 4 losses como base, depois coloca WIN no final (mais recente)
        history = self._make_history(4, 10)
        # WIN após os losses quebra a sequência
        history.append({"result": "WIN", "exit_time": datetime.now(timezone.utc).isoformat()})
        active, reason = trading_cooldown(history)
        self.assertFalse(active)

    def test_empty_history_no_cooldown(self):
        from risk import trading_cooldown
        active, reason = trading_cooldown([])
        self.assertFalse(active)


class TestSigmaShrinkage(unittest.TestCase):
    """
    Testa a estimativa de sigma em SigmaCalibrator.get_adjusted_sigma().

    O sigma é agora ESTIMADO a partir dos resíduos, com shrinkage para o
    sigma base. A versão anterior somava um "adjustment" que só sabia
    aumentar (max(0, media_abs - 2.0) * 0.6): com o erro real de 1.5°C o
    ajuste era sempre 0 e o sigma nunca saía do chute inicial.
    """

    def setUp(self):
        from sigma_calibrator import SigmaCalibrator
        self.cal = SigmaCalibrator()

    def _entries(self, values, key="residual", n=None):
        vals = values if isinstance(values, list) else [values] * (n or 1)
        return [{key: v, "error": abs(v), "timestamp": f"2026-01-{i+1:02d}"}
                for i, v in enumerate(vals)]

    def test_no_data_keeps_base_sigma(self):
        sigma = self.cal.get_adjusted_sigma("unknown-city", 4.0, "ABOVE")
        self.assertEqual(sigma, 4.0)

    def test_under_min_samples_keeps_base_sigma(self):
        """Amostra insuficiente: não inventa estimativa."""
        self.cal.calibration_data["test-few"] = {
            "ABOVE": {"errors": self._entries(3.0, n=3)}
        }
        self.assertEqual(self.cal.get_adjusted_sigma("test-few", 4.0, "ABOVE"), 4.0)

    def test_sigma_can_go_DOWN(self):
        """
        O caso que a versão antiga era incapaz de tratar: resíduos pequenos
        têm de REDUZIR o sigma. Aqui os resíduos são ±0.5°C com sigma base
        de 4.0 — o resultado tem de ficar abaixo de 4.0.
        """
        residuals = [0.5, -0.5] * 15
        self.cal.calibration_data["test-down"] = {
            "ABOVE": {"errors": self._entries(residuals)}
        }
        sigma = self.cal.get_adjusted_sigma("test-down", 4.0, "ABOVE")
        self.assertLess(sigma, 4.0)
        self.assertGreaterEqual(sigma, 1.0)   # respeita SIGMA_MIN

    def test_sigma_goes_up_with_large_residuals(self):
        residuals = [6.0, -6.0] * 15
        self.cal.calibration_data["test-up"] = {
            "ABOVE": {"errors": self._entries(residuals)}
        }
        sigma = self.cal.get_adjusted_sigma("test-up", 4.0, "ABOVE")
        self.assertGreater(sigma, 4.0)

    def test_shrinkage_weight_grows_with_sample(self):
        """Amostra maior → estimativa empírica pesa mais que o base."""
        residuals_small = [1.0, -1.0] * 3     # n=6
        residuals_big = [1.0, -1.0] * 20      # n=40
        self.cal.calibration_data["test-w-small"] = {
            "ABOVE": {"errors": self._entries(residuals_small)}
        }
        self.cal.calibration_data["test-w-big"] = {
            "ABOVE": {"errors": self._entries(residuals_big)}
        }
        s_small = self.cal.get_adjusted_sigma("test-w-small", 4.0, "ABOVE")
        s_big = self.cal.get_adjusted_sigma("test-w-big", 4.0, "ABOVE")
        # ambos abaixo do base, mas o de amostra grande mais perto do empírico
        self.assertLess(s_big, s_small)

    def test_legacy_entries_without_residual_still_work(self):
        """Dados gravados antes da v4 só têm |erro| — usa RMS como proxy."""
        self.cal.calibration_data["test-legacy"] = {
            "ABOVE": {"errors": [
                {"error": 2.0, "timestamp": f"2026-01-{i+1:02d}"} for i in range(10)
            ]}
        }
        sigma = self.cal.get_adjusted_sigma("test-legacy", 4.0, "ABOVE")
        self.assertLess(sigma, 4.0)
        self.assertGreater(sigma, 2.0)

    def test_respects_sigma_bounds(self):
        from config import SIGMA_MIN, SIGMA_MAX
        self.cal.calibration_data["test-tiny"] = {
            "ABOVE": {"errors": self._entries([0.01, -0.01] * 20)}
        }
        self.cal.calibration_data["test-huge"] = {
            "ABOVE": {"errors": self._entries([50.0, -50.0] * 20)}
        }
        self.assertGreaterEqual(self.cal.get_adjusted_sigma("test-tiny", 4.0, "ABOVE"), SIGMA_MIN)
        self.assertLessEqual(self.cal.get_adjusted_sigma("test-huge", 4.0, "ABOVE"), SIGMA_MAX)


class TestMLAdjusterClamp(unittest.TestCase):
    """
    O blend do ML não pode afastar a probabilidade da física além do
    permitido. Sem esta trava, o SGD saturado em 1.0 transformava
    P(bucket)=0.002 em 0.30 — o piso do blend, não um sinal.
    """

    def test_blend_desligado_por_default(self):
        from config import ML_BLEND_WEIGHT
        self.assertEqual(ML_BLEND_WEIGHT, 0.0)

    def test_adjust_probability_e_identidade_com_peso_zero(self):
        from ml_adjuster import MLProbabilityAdjuster
        adj = MLProbabilityAdjuster()
        for p in (0.0019, 0.05, 0.5, 0.97):
            self.assertEqual(adj.adjust_probability(p, 1, "los angeles", None), p)

    def test_clamp_limita_desvio_absoluto(self):
        from ml_adjuster import MLProbabilityAdjuster
        from config import ML_MAX_DEVIATION
        clamp = MLProbabilityAdjuster._clamp_to_physical
        self.assertAlmostEqual(clamp(0.90, 0.50), 0.50 + ML_MAX_DEVIATION, places=6)
        self.assertAlmostEqual(clamp(0.10, 0.50), 0.50 - ML_MAX_DEVIATION, places=6)

    def test_clamp_limita_razao_para_prob_pequena(self):
        """O caso real de Los Angeles: 0.0019 nunca pode virar 0.30."""
        from ml_adjuster import MLProbabilityAdjuster
        from config import ML_MAX_RATIO
        clamp = MLProbabilityAdjuster._clamp_to_physical
        out = clamp(0.3013, 0.0019)
        self.assertLessEqual(out, 0.0019 * ML_MAX_RATIO + 1e-9)
        self.assertLess(out, 0.01)


class TestBucketGuardrails(unittest.TestCase):
    """
    Gate de sanidade física: comprar YES num bucket exige que a previsão
    esteja dentro ou perto dele. Reproduz o trade real de Los Angeles de
    2026-08-01 (previsão 36.22°C, bucket 78-79°F ≈ 25.6-26.1°C).
    """

    LA_MARKET = {
        "condition": "RANGE2", "target_temp": 78.5, "price": 0.275,
        "day_offset": 1, "unit": "F", "target_lo": 78.0, "target_hi": 79.0,
    }

    def test_yes_bloqueado_quando_forecast_longe_do_bucket(self):
        from risk import check_guardrails
        ok, reason = check_guardrails(self.LA_MARKET, 0.3013, 36.22, sigma=4.0, side="YES")
        self.assertFalse(ok)
        self.assertEqual(reason, "forecast_fora_do_bucket")

    def test_no_bloqueado_quando_forecast_dentro_do_bucket(self):
        from risk import check_guardrails
        market = dict(self.LA_MARKET, price=0.60)
        # forecast 25.8C está dentro de 78-79F (25.56-26.11C)
        ok, reason = check_guardrails(market, 0.20, 25.8, sigma=4.0, side="NO")
        self.assertFalse(ok)
        self.assertEqual(reason, "forecast_dentro_do_bucket")

    def test_bucket_distance_dentro_e_fora(self):
        from risk import _bucket_distance
        inside, dist = _bucket_distance(25.8, "RANGE2", 25.83, "F", 78.0, 79.0)
        self.assertTrue(inside)
        inside, dist = _bucket_distance(36.22, "RANGE2", 25.83, "F", 78.0, 79.0)
        self.assertFalse(inside)
        self.assertGreater(dist, 9.0)

    def test_edge_alto_demais_em_range2(self):
        from risk import check_guardrails
        market = dict(self.LA_MARKET, price=0.05)
        # prob 0.60 dentro do bucket, mas edge 0.55 > MAX_EDGE_RANGE2
        ok, reason = check_guardrails(market, 0.60, 25.8, sigma=4.0, side="YES")
        self.assertFalse(ok)
        self.assertEqual(reason, "edge_alto_demais")


class TestAlreadyTradedPorLado(unittest.TestCase):
    """
    Negociar um lado não pode bloquear o outro: _key_variants incluía a
    chave sem lado nos dois conjuntos, então a interseção na base fazia
    already_traded("X_YES") casar com um trade "X_NO".
    """

    HISTORY = [{
        "market_id": "toronto|2026-06-02|EXACT|25|C_NO",
        "market_key": "toronto|2026-06-02|EXACT|25|C",
        "side": "NO", "city": "Toronto", "market_date": "2026-06-02",
        "type": "EXACT", "unit": "C", "target": 25.0, "result": "LOSS",
    }]
    BASE = "toronto|2026-06-02|EXACT|25|C"

    def test_mesmo_lado_e_detectado(self):
        from bankroll import already_traded
        self.assertTrue(already_traded(self.HISTORY, self.BASE + "_NO"))

    def test_lado_oposto_nao_e_bloqueado(self):
        from bankroll import already_traded
        self.assertFalse(already_traded(self.HISTORY, self.BASE + "_YES"))

    def test_consulta_sem_lado_casa_qualquer_lado(self):
        from bankroll import already_traded
        self.assertTrue(already_traded(self.HISTORY, self.BASE))

    def test_trade_legado_sem_side_bloqueia_ambos(self):
        from bankroll import already_traded
        legacy = [{"market_id": self.BASE, "market_key": self.BASE, "result": "LOSS"}]
        self.assertTrue(already_traded(legacy, self.BASE + "_YES"))
        self.assertTrue(already_traded(legacy, self.BASE + "_NO"))


class TestCalibracaoLadoNO(unittest.TestCase):
    """
    analytics/statistics emparelhava model_prob (P(YES)) com o resultado do
    TRADE, invertendo o sinal em todo trade NO — 73% do histórico. Era a
    origem do ECE de 0.894 que derrubou o health score para 55/RED.
    """

    def _ds(self, trades):
        from analytics.dataset import build_dataset_from_history
        return build_dataset_from_history(trades, start_balance=100.0)

    def test_no_vencedor_com_prob_baixa_tem_brier_baixo(self):
        from analytics.statistics import brier_score
        # NO a P(YES)=0.05 que GANHOU: P(lado)=0.95, acertou → erro pequeno
        ds = self._ds([{"result": "WIN", "side": "NO", "model_prob": 0.05,
                        "pnl": 1.0, "stake": 1.0}])
        self.assertLess(brier_score(ds), 0.01)

    def test_yes_vencedor_com_prob_alta_tem_brier_baixo(self):
        from analytics.statistics import brier_score
        ds = self._ds([{"result": "WIN", "side": "YES", "model_prob": 0.95,
                        "pnl": 1.0, "stake": 1.0}])
        self.assertLess(brier_score(ds), 0.01)

    def test_pares_ficam_alinhados_quando_falta_model_prob(self):
        from analytics.statistics import probabilities, outcomes
        ds = self._ds([
            {"result": "WIN", "side": "NO", "model_prob": 0.05, "pnl": 1.0, "stake": 1.0},
            {"result": "LOSS", "side": "YES", "pnl": -1.0, "stake": 1.0},   # sem model_prob
            {"result": "WIN", "side": "YES", "model_prob": 0.90, "pnl": 1.0, "stake": 1.0},
        ])
        self.assertEqual(len(probabilities(ds)), len(outcomes(ds)))
        self.assertEqual(len(probabilities(ds)), 2)


class TestBranchDeDeployProtegida(unittest.TestCase):
    """Backup do bankroll nunca pode ir para a branch de deploy."""

    def test_main_e_recusada(self):
        from github_sync import _safe_branch
        self.assertEqual(_safe_branch("main"), "data-backup")
        self.assertEqual(_safe_branch("master"), "data-backup")
        self.assertEqual(_safe_branch("MAIN"), "data-backup")

    def test_branch_de_dados_e_aceita(self):
        from github_sync import _safe_branch
        self.assertEqual(_safe_branch("data-backup"), "data-backup")
        self.assertEqual(_safe_branch("bankroll-data"), "bankroll-data")

    def test_vazio_cai_no_default(self):
        from github_sync import _safe_branch
        self.assertEqual(_safe_branch(""), "data-backup")
        self.assertEqual(_safe_branch(None), "data-backup")


class TestFiltrosDeMercado(unittest.TestCase):
    """MIN_MARKET_LIQUIDITY/VOLUME e MAX_IMPLIED_SPREAD nunca eram lidos."""

    def test_spread_alto_rejeitado(self):
        from gamma_parser import market_is_healthy
        ok, reason = market_is_healthy(0.50, 0.60)   # soma 1.10
        self.assertFalse(ok)
        self.assertIn("spread_alto", reason)

    def test_liquidez_baixa_rejeitada(self):
        from gamma_parser import market_is_healthy
        ok, reason = market_is_healthy(0.30, 0.70, {"liquidity": "5"})
        self.assertFalse(ok)
        self.assertIn("liquidez_baixa", reason)

    def test_volume_baixo_rejeitado(self):
        from gamma_parser import market_is_healthy
        ok, reason = market_is_healthy(0.30, 0.70, {"liquidity": "5000", "volume": "10"})
        self.assertFalse(ok)
        self.assertIn("volume_baixo", reason)

    def test_mercado_saudavel_aceito(self):
        from gamma_parser import market_is_healthy
        ok, reason = market_is_healthy(0.30, 0.70, {"liquidity": "5000", "volume": "9000"})
        self.assertTrue(ok)

    def test_liquidez_ausente_nao_bloqueia(self):
        from gamma_parser import market_is_healthy
        ok, _ = market_is_healthy(0.30, 0.70, {})
        self.assertTrue(ok)

    def test_clob_tokens_extraidos(self):
        from gamma_parser import _parse_clob_tokens
        yes, no = _parse_clob_tokens({"clobTokenIds": '["111", "222"]'})
        self.assertEqual((yes, no), ("111", "222"))
        self.assertEqual(_parse_clob_tokens({}), ("", ""))


class TestExecucaoRealNaoImplementada(unittest.TestCase):
    """O stub anterior devolvia ok=True e o bankroll registrava posições
    que não existiam."""

    def test_levanta_not_implemented(self):
        from real_execution import execute_real_trade
        with self.assertRaises(NotImplementedError):
            execute_real_trade({"yes_token_id": "1"}, "YES", 4.0)


class TestCidadesAtivas(unittest.TestCase):
    """Cidade inativa não gera entrada mas continua liquidável."""

    def test_la_fora_de_cities(self):
        from config import CITIES, ALL_CITIES
        slugs = {c["slug"] for c in CITIES}
        all_slugs = {c["slug"] for c in ALL_CITIES}
        self.assertNotIn("los-angeles", slugs)
        self.assertIn("los-angeles", all_slugs)

    def test_la_ainda_tem_coordenadas_para_settlement(self):
        from settlement import _get_city_coordinates
        lat, lon = _get_city_coordinates("Los Angeles")
        self.assertIsNotNone(lat)
        self.assertIsNotNone(lon)

    def test_station_coords_tem_prioridade(self):
        from config import resolution_coords
        city = {"lat": 34.0522, "lon": -118.2437,
                "station_lat": 33.9416, "station_lon": -118.4085}
        self.assertEqual(resolution_coords(city), (33.9416, -118.4085))
        self.assertEqual(resolution_coords({"lat": 1.0, "lon": 2.0}), (1.0, 2.0))


class TestEstacoesDoAno(unittest.TestCase):
    def test_hemisferio_norte(self):
        from analytics.dataset import _season
        self.assertEqual(_season(7), "SUMMER")
        self.assertEqual(_season(1), "WINTER")
        self.assertEqual(_season(4), "SPRING")
        self.assertEqual(_season(10), "AUTUMN")


class TestSettleTradeRemovida(unittest.TestCase):
    def test_levanta_not_implemented(self):
        from settlement import settle_trade
        with self.assertRaises(NotImplementedError):
            settle_trade({}, {})


class TestHealthStaleness(unittest.TestCase):
    """Um health.json velho não pode continuar a governar o kelly_factor."""

    def test_health_velho_e_ignorado(self):
        import json, tempfile, os
        from pathlib import Path
        import analytics.storage as storage

        original = storage.HEALTH_FILE
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "health.json"
            path.write_text(json.dumps({
                "schema": 1,
                "generated_at": "2020-01-01T00:00:00+00:00",
                "checksum": "x",
                "payload": {"kelly_factor": 0.2},
            }), encoding="utf-8")
            storage.HEALTH_FILE = path
            try:
                self.assertIsNone(storage.load_health())
            finally:
                storage.HEALTH_FILE = original

    def test_factor_neutro_sem_health(self):
        from risk import apply_health_factor
        import analytics.storage as storage
        original = storage.HEALTH_FILE
        storage.HEALTH_FILE = storage.BASE / "__inexistente__.json"
        try:
            stake, reason = apply_health_factor(4.0)
            self.assertEqual(stake, 4.0)
        finally:
            storage.HEALTH_FILE = original


class TestValidacaoPosCorte(unittest.TestCase):
    """
    O histórico anterior ao fix de fonte de dados (coordenada de LA) não
    pode contar para a validação — validacao.py agora filtra por
    entry_time >= VALIDATION_CUTOFF_ISO.
    """

    def test_trade_antigo_excluido(self):
        from validacao import _pos_corte
        antigo = {"entry_time": "2026-06-01T10:00:00+00:00"}
        self.assertFalse(_pos_corte(antigo))

    def test_trade_novo_incluido(self):
        from validacao import _pos_corte
        novo = {"entry_time": "2026-08-02T10:00:00+00:00"}
        self.assertTrue(_pos_corte(novo))

    def test_sem_entry_time_e_excluido_por_seguranca(self):
        from validacao import _pos_corte
        self.assertFalse(_pos_corte({}))

    def test_criterios_batem_com_o_readme(self):
        from validacao import N_MIN_VALIDACAO, CI_LOWER_MIN, MIN_RANGE2_TRADES
        self.assertEqual(N_MIN_VALIDACAO, 110)
        self.assertEqual(CI_LOWER_MIN, 0.52)
        self.assertEqual(MIN_RANGE2_TRADES, 10)

    def test_veredito_reprovado_por_n_baixo_mesmo_com_wr_perfeito(self):
        """109 vitórias em 109 não aprova — falta amostra (README exige 110)."""
        from validacao import _veredito, N_MIN_VALIDACAO
        veredito, detalhe = _veredito(
            n=N_MIN_VALIDACAO - 1, wins=N_MIN_VALIDACAO - 1,
            brier=0.10, edge_realizado_pct=5.0, n_range2=10,
        )
        self.assertIn("REPROVADO", veredito)

    def test_veredito_reprovado_por_poucos_range2(self):
        from validacao import _veredito, N_MIN_VALIDACAO
        veredito, detalhe = _veredito(
            n=N_MIN_VALIDACAO, wins=int(N_MIN_VALIDACAO * 0.6),
            brier=0.10, edge_realizado_pct=5.0, n_range2=3,
        )
        self.assertIn("REPROVADO", veredito)
        self.assertIn("RANGE2", detalhe)

    def test_veredito_aprovado_quando_todos_criterios_batem(self):
        from validacao import _veredito, N_MIN_VALIDACAO
        veredito, detalhe = _veredito(
            n=N_MIN_VALIDACAO, wins=int(N_MIN_VALIDACAO * 0.65),
            brier=0.15, edge_realizado_pct=3.0, n_range2=15,
        )
        self.assertIn("APROVADO", veredito)

    def test_relatorio_atual_mostra_zero_pos_corte(self):
        """No bankroll real (132 trades, todos pré-fix), o relatório tem
        que dar 0 fechados pós-corte, não os 128 antigos."""
        from validacao import gerar_relatorio
        r = gerar_relatorio(enviar_telegram=False)
        self.assertIn("Fechados: <b>0</b>/110", r)
        self.assertIn("AGUARDANDO", r)
        self.assertIn("excluídos", r)


class TestSemBoostPorCidade(unittest.TestCase):
    """O boost hardcoded de Seoul/Tokyo/Madrid foi removido."""

    def test_city_nao_altera_o_fator(self):
        from risk import apply_health_factor
        for city in ("Seoul", "Tokyo", "Madrid", "Chicago", None):
            self.assertEqual(
                apply_health_factor(4.0, city=city),
                apply_health_factor(4.0),
            )

    def test_fator_nao_passa_de_1(self):
        import analytics.storage as storage
        from risk import apply_health_factor
        original = storage.load_health
        storage.load_health = lambda *a, **k: {"kelly_factor": 1.5}
        # risk importou load_health por nome — corrige o binding local
        import risk
        risk_original = risk.load_health
        risk.load_health = storage.load_health
        try:
            stake, reason = apply_health_factor(4.0)
            self.assertLessEqual(stake, 4.0)
        finally:
            storage.load_health = original
            risk.load_health = risk_original


class TestSettlementCityLookup(unittest.TestCase):
    """Testa _get_city_coordinates com slug/display/aliases."""

    def test_lookup_by_slug(self):
        from settlement import _get_city_coordinates
        lat, lon = _get_city_coordinates("new-york")
        self.assertIsNotNone(lat)
        self.assertAlmostEqual(lat, 40.7128, places=2)

    def test_lookup_by_display(self):
        from settlement import _get_city_coordinates
        lat, lon = _get_city_coordinates("New York")
        self.assertIsNotNone(lat)
        self.assertAlmostEqual(lat, 40.7128, places=2)

    def test_lookup_by_alias(self):
        from settlement import _get_city_coordinates
        lat, lon = _get_city_coordinates("nyc")
        self.assertIsNotNone(lat)
        self.assertAlmostEqual(lat, 40.7128, places=2)

    def test_unknown_city_returns_none(self):
        from settlement import _get_city_coordinates
        lat, lon = _get_city_coordinates("nonexistent-city-xyz")
        self.assertIsNone(lat)
        self.assertIsNone(lon)


class TestConfigParametersFromRisk(unittest.TestCase):
    """Verifica que risk.py importa constantes de config (não hardcoded)."""

    def test_fee_rate_matches_config(self):
        from risk import FEE_RATE
        from config import FEE_RATE as CFG_FEE
        self.assertEqual(FEE_RATE, CFG_FEE)

    def test_min_prob_range2_matches_config(self):
        from risk import MIN_PROB_RANGE2
        from config import MIN_PROB_RANGE2 as CFG
        self.assertEqual(MIN_PROB_RANGE2, CFG)

    def test_min_edge_range2_matches_config(self):
        from risk import MIN_EDGE_RANGE2
        from config import MIN_EDGE_RANGE2 as CFG
        self.assertEqual(MIN_EDGE_RANGE2, CFG)

    def test_max_prob_for_no_matches_config(self):
        from risk import MAX_PROB_FOR_NO
        from config import MAX_PROB_FOR_NO as CFG
        self.assertEqual(MAX_PROB_FOR_NO, CFG)


class TestRuntimeCities(unittest.TestCase):
    """Garante compatibilidade entre cities.json e bot.process_city."""

    def test_cities_have_legacy_name_field(self):
        from config import CITIES

        self.assertGreater(len(CITIES), 0)
        for city in CITIES:
            self.assertTrue(city.get("name"))
            self.assertTrue(city.get("slug"))
            self.assertIn("lat", city)
            self.assertIn("lon", city)


class TestNotificadorContext(unittest.TestCase):
    """Verifica que _build_context() usa config real, não hardcoded."""

    def test_context_has_correct_version(self):
        from notificador import _build_context
        ctx = _build_context()
        self.assertIn("v5.1", ctx)
        self.assertNotIn("v4", ctx)

    def test_context_has_correct_position_cap(self):
        from config import MAX_POSITION
        from notificador import _build_context
        ctx = _build_context()
        self.assertIn(f"${MAX_POSITION:.0f}", ctx)
        self.assertNotIn("Cap $2", ctx)

    def test_context_has_correct_prob(self):
        from config import MIN_PROB_ABOVE_BELOW
        from notificador import _build_context
        ctx = _build_context()
        # Deve conter a prob real (72%), não a stale (80%)
        filter_lines = [line for line in ctx.splitlines() if "Filtros ativos:" in line]
        self.assertTrue(filter_lines)
        self.assertIn(f"{MIN_PROB_ABOVE_BELOW*100:.0f}%", filter_lines[0])
        self.assertNotIn("prob >= 80%", filter_lines[0])

    def test_context_mentions_cooldown(self):
        from notificador import _build_context
        ctx = _build_context()
        self.assertIn("cooldown", ctx.lower())


class TestSigmaFromConfig(unittest.TestCase):
    """Verifica SigmaCalibrator usa SIGMA_MIN/SIGMA_MAX de config."""

    def test_sigma_min_from_config(self):
        from sigma_calibrator import SIGMA_MIN
        from config import SIGMA_MIN as CFG
        self.assertEqual(SIGMA_MIN, CFG)

    def test_sigma_max_from_config(self):
        from sigma_calibrator import SIGMA_MAX
        from config import SIGMA_MAX as CFG
        self.assertEqual(SIGMA_MAX, CFG)


class TestSettlementRetryConfig(unittest.TestCase):
    """Verifica que settlement importa configs certas."""

    def test_max_open_trade_days_from_config(self):
        from settlement import MAX_OPEN_TRADE_DAYS
        from config import MAX_OPEN_TRADE_DAYS as CFG
        self.assertEqual(MAX_OPEN_TRADE_DAYS, CFG)

    def test_settle_temp_retries_from_config(self):
        from settlement import SETTLE_TEMP_RETRIES
        from config import SETTLE_TEMP_RETRIES as CFG
        self.assertEqual(SETTLE_TEMP_RETRIES, CFG)

class TestPaperExecution(unittest.TestCase):
    def test_simulate_buy_walks_asks_and_computes_average(self):
        from paper_execution import simulate_buy_from_levels
        levels = [
            {"price": 0.50, "size": 2.0},
            {"price": 0.55, "size": 10.0},
        ]
        result = simulate_buy_from_levels(levels, stake=2.55, token_id="tok", side="YES")
        self.assertTrue(result.ok, result.reason)
        self.assertAlmostEqual(result.filled_cost, 2.55, places=4)
        self.assertAlmostEqual(result.shares, 2.0 + (1.55 / 0.55), places=4)
        self.assertGreater(result.avg_price, 0.50)
        self.assertEqual(result.levels_used, 2)

    def test_simulate_buy_blocks_insufficient_fill(self):
        from paper_execution import simulate_buy_from_levels
        levels = [{"price": 0.50, "size": 1.0}]
        result = simulate_buy_from_levels(levels, stake=2.00, token_id="tok", side="YES")
        self.assertFalse(result.ok)
        self.assertIn("fill insuficiente", result.reason)


class TestDecisionLog(unittest.TestCase):
    def test_records_and_summarizes_decisions(self):
        import decision_log

        old_path = decision_log.DECISION_LOG_FILE
        with tempfile.TemporaryDirectory() as tmp:
            decision_log.DECISION_LOG_FILE = os.path.join(tmp, "decisions.jsonl")
            self.assertTrue(decision_log.record_decision(
                "blocked", "paper_execution_blocked",
                city="New York", side="YES",
                market={"market_id": "m1", "market_date": "2026-06-29"},
                detail="slippage alto",
            ))
            events = decision_log.load_decisions()
            self.assertEqual(len(events), 1)
            summary = decision_log.summarize_decisions(events)
            self.assertEqual(summary["blocked_count"], 1)
            self.assertEqual(summary["by_reason"]["paper_execution_blocked"], 1)
        decision_log.DECISION_LOG_FILE = old_path

    def test_execution_summary_separates_orderbook_and_legacy(self):
        from decision_log import trade_execution_summary

        summary = trade_execution_summary([
            {"paper_execution": True, "stake": 2.0, "filled_cost": 2.0, "slippage": 0.01, "fill_ratio": 1.0, "result": "OPEN"},
            {"stake": 3.0, "result": "LOSS"},
        ])
        self.assertEqual(summary["paper_orderbook"], 1)
        self.assertEqual(summary["legacy_paper"], 1)
        self.assertEqual(summary["avg_slippage"], 0.01)
        self.assertEqual(summary["avg_fill_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
