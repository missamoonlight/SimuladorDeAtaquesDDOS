from __future__ import annotations

import random
import unittest

from aplicacion.modelos.perfil_servidor import demo_profile
from aplicacion.modelos.configuracion_simulacion import MITIGATION_NAMES, MitigationConfig, SimulationConfig
from aplicacion.simulacion.modelo_capacidad import CapacityModel
from aplicacion.simulacion.motor_simulacion import SimulationEngine


class SimulationModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SimulationConfig(
            initial_users=20,
            max_users=1000,
            duration_seconds=12,
            requests_per_user=1,
            scenario="Repentino",
            sudden_ramp_seconds=5,
            seed=123,
            real_time=False,
            mitigation=MitigationConfig(rate_limiting=35, blacklisting=0, scaling=0, captcha=0),
        )

    def test_capacity_estimate_uses_cpu_and_memory(self) -> None:
        model = CapacityModel(demo_profile(), self.config)
        estimate = model.estimate()
        self.assertGreater(estimate.cpu_requests_per_second, 0)
        self.assertGreater(estimate.memory_users, 0)
        self.assertGreater(estimate.estimated_users, 0)
        self.assertGreater(estimate.estimated_requests_per_second, 0)
        self.assertFalse(hasattr(model, "network_capacity_mbps"))

    def test_network_consumption_is_estimated_without_link_capacity(self) -> None:
        model = CapacityModel(demo_profile(), self.config)
        rx, tx = model.network_consumption_mbps(10, 2)
        self.assertAlmostEqual(rx, 10 * model.average_request_bytes * 8 / 1_000_000)
        self.assertAlmostEqual(tx, 2 * model.average_response_bytes * 8 / 1_000_000)
        result = SimulationEngine(demo_profile(), self.config).run()
        self.assertTrue(all(sample.network_rx_mbps >= 0 for sample in result.samples))
        self.assertTrue(all(sample.network_tx_mbps >= 0 for sample in result.samples))

    def test_sudden_scenario_is_bounded(self) -> None:
        result = SimulationEngine(demo_profile(), self.config).run()
        self.assertLessEqual(max(sample.users for sample in result.samples), 1000)
        for sample in result.samples:
            self.assertGreaterEqual(sample.processed_requests_s, 0)
            self.assertGreaterEqual(sample.generated_requests_s, 0)
            self.assertTrue(0 <= sample.cpu_percent <= 100)
            self.assertTrue(0 <= sample.ram_percent <= 100)
            self.assertTrue(0 <= sample.saturation_percent <= 100)
            self.assertFalse(hasattr(sample, "traffic_rx_mbps"))

    def test_rate_limiting_limits_admission_and_processing_stays_with_capacity(self) -> None:
        config = self.config
        config.duration_seconds = 20
        config.mitigation.anomaly_window_seconds = 1
        result = SimulationEngine(demo_profile(), config).run()
        self.assertIsNotNone(result.detected_at)
        detected_sample = result.samples[result.detected_at - 1]
        self.assertLessEqual(detected_sample.effective_users, detected_sample.users)
        self.assertLessEqual(detected_sample.processed_requests_s, detected_sample.capacity_rps)
        self.assertGreater(detected_sample.requests_limited, 0)

    def test_each_mitigation_is_selectable_and_local(self) -> None:
        for name in MITIGATION_NAMES:
            with self.subTest(mitigation=name):
                config = SimulationConfig(
                    initial_users=20,
                    max_users=100,
                    duration_seconds=12,
                    scenario="Repentino",
                    seed=123,
                    real_time=False,
                    mitigation=MitigationConfig(selected=(name,), anomaly_window_seconds=1),
                )
                result = SimulationEngine(demo_profile(), config).run()
                self.assertTrue(result.samples)
                self.assertTrue(all(sample.users <= config.max_users for sample in result.samples))
                self.assertTrue(all(sample.generated_requests_s >= 0 for sample in result.samples))

    def test_cdn_and_edge_reduce_requests_reaching_server(self) -> None:
        config = SimulationConfig(
            initial_users=20,
            max_users=1000,
            duration_seconds=20,
            scenario="Repentino",
            seed=123,
            real_time=False,
            mitigation=MitigationConfig(
                selected=("CDN / Caching", "Edge / Scrubbing"),
                cdn_hit_ratio=80,
                edge_filter_percent=50,
                anomaly_window_seconds=1,
            ),
        )
        result = SimulationEngine(demo_profile(), config).run()
        self.assertIsNotNone(result.detected_at)
        sample = result.samples[-1]
        self.assertLess(sample.requests_origin, sample.requests_generated)
        self.assertGreater(sample.requests_cache, 0)

    def test_edge_scrubbing_filters_malicious_traffic_before_the_origin(self) -> None:
        config = SimulationConfig(
            initial_users=10, max_users=100, duration_seconds=5,
            mitigation=MitigationConfig(selected=("Edge / Scrubbing",), edge_filter_percent=90),
        )
        engine = SimulationEngine(demo_profile(), config)
        metrics = engine._pipeline(
            1, 100, 100, 10, 90, 10, 90, False, random.Random(1), 1.0, None, [],
        )
        self.assertAlmostEqual(metrics["requests_blocked"], 81.0)
        self.assertAlmostEqual(metrics["legitimate_preserved"], 10.0)

    def test_rate_limit_applies_a_separate_allowance_to_each_source(self) -> None:
        config = SimulationConfig(
            initial_users=1, max_users=10, duration_seconds=5,
            mitigation=MitigationConfig(selected=("Rate Limiting",), rate_limit_rps=2),
        )
        engine = SimulationEngine(demo_profile(), config)
        metrics = engine._pipeline(
            1, 3, 20, 10, 10, 1, 2, False, random.Random(1), 1.0, None,
            [("Legítimo", 1, 10), ("Malicioso", 1, 10), ("Malicioso", 2, 0)],
        )
        self.assertEqual(metrics["requests_limited"], 16)

    def test_autoscaling_increases_model_capacity_once_per_interval(self) -> None:
        config = SimulationConfig(
            initial_users=20,
            max_users=1000,
            duration_seconds=12,
            scenario="Repentino",
            seed=123,
            real_time=False,
            mitigation=MitigationConfig(selected=("Auto Scaling",), autoscaling_max_instances=3, autoscaling_time_seconds=1),
        )
        result = SimulationEngine(demo_profile(), config).run()
        self.assertGreaterEqual(max(sample.instances for sample in result.samples), 2)
        self.assertLessEqual(max(sample.instances for sample in result.samples), 3)


if __name__ == "__main__":
    unittest.main()
