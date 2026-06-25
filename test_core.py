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
    """Testa shrinkage em SigmaCalibrator.get_adjusted_sigma()."""

    def setUp(self):
        from sigma_calibrator import SigmaCalibrator
        self.cal = SigmaCalibrator()

    def test_no_adjustment_without_data(self):
        """Sem dados: sigma = base_sigma (adjustment = 0)."""
        sigma = self.cal.get_adjusted_sigma("unknown-city", 4.0, "ABOVE")
        self.assertEqual(sigma, 4.0)

    def test_shrinkage_under_5_samples(self):
        """n < 5: adjustment inteiramente suprimido (0)."""
        city = "test-shrink"
        cond = "ABOVE"
        self.cal.calibration_data[city] = {
            cond: {
                "errors": [{"error": 3.0, "timestamp": "2026-01-01"}] * 3,
                "sigma_adjustment": 1.0,
            }
        }
        sigma = self.cal.get_adjusted_sigma(city, 4.0, cond)
        # n=3 < 5 → adjustment=0 → sigma=4.0
        self.assertEqual(sigma, 4.0)

    def test_shrinkage_ramp_5_to_19(self):
        """5 ≤ n < 20: rampa linear adjustment * (n-5)/15."""
        city = "test-ramp"
        cond = "ABOVE"
        n = 10
        self.cal.calibration_data[city] = {
            cond: {
                "errors": [{"error": 3.0, "timestamp": "2026-01-01"}] * n,
                "sigma_adjustment": 1.5,
            }
        }
        sigma = self.cal.get_adjusted_sigma(city, 4.0, cond)
        # (10-5)/15 = 5/15 = 1/3; adjustment = 1.5 * 1/3 = 0.5
        expected = 4.0 + 0.5
        self.assertAlmostEqual(sigma, expected, places=3)

    def test_full_adjustment_20_plus(self):
        """n ≥ 20: adjustment aplicado integralmente."""
        city = "test-full"
        cond = "ABOVE"
        self.cal.calibration_data[city] = {
            cond: {
                "errors": [{"error": 3.0, "timestamp": "2026-01-01"}] * 25,
                "sigma_adjustment": 1.5,
            }
        }
        sigma = self.cal.get_adjusted_sigma(city, 4.0, cond)
        self.assertAlmostEqual(sigma, 5.5, places=3)


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
        self.assertIn(f"{MIN_PROB_ABOVE_BELOW*100:.0f}%", ctx)
        self.assertNotIn("80%", ctx)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
