from __future__ import annotations

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
            request_bytes=2048,
            response_bytes=16384,
            scenario="Repentino",
            sudden_ramp_seconds=5,
            mitigation=MitigationConfig(rate_limiting=35, blacklisting=0, scaling=0, captcha=0),
        )

    def test_traffic_formula(self) -> None:
        traffic = CapacityModel(demo_profile(), self.config).traffic_mbps(1000)
        self.assertAlmostEqual(traffic, 147.456, places=3)
        self.assertNotEqual(traffic, 14745.6)

    def test_sudden_scenario_is_bounded(self) -> None:
        result = SimulationEngine(demo_profile(), self.config).run()
        self.assertLessEqual(max(sample.users for sample in result.samples), 1000)
        self.assertNotIn(100000, [sample.users for sample in result.samples])
        self.assertLessEqual(max(sample.generated_traffic_mbps for sample in result.samples), 147.456)
        for sample in result.samples:
            self.assertGreaterEqual(sample.processed_requests_s, 0)
            self.assertGreaterEqual(sample.processed_traffic_mbps, 0)
            self.assertTrue(0 <= sample.cpu_percent <= 100)
            self.assertTrue(0 <= sample.ram_percent <= 100)
            self.assertTrue(0 <= sample.saturation_percent <= 100)

    def test_rate_limiting_reduces_processed_requests_only(self) -> None:
        config = self.config
        config.duration_seconds = 2
        config.mitigation.anomaly_window_seconds = 1
        result = SimulationEngine(demo_profile(), config).run()
        detected_sample = next(sample for sample in result.samples if sample.state in {"ANOMALÍA DETECTADA", "MITIGACIÓN ACTIVA", "RECUPERADO"})
        self.assertEqual(detected_sample.users, detected_sample.effective_users)
        self.assertLessEqual(detected_sample.processed_requests_s, self.config.mitigation.rate_limit_rps)
        self.assertAlmostEqual(detected_sample.requests_limited, detected_sample.generated_requests_s - detected_sample.processed_requests_s, places=6)

    def test_each_mitigation_is_selectable_and_local(self) -> None:
        for name in MITIGATION_NAMES:
            with self.subTest(mitigation=name):
                config = SimulationConfig(
                    initial_users=20,
                    max_users=100,
                    duration_seconds=2,
                    scenario="Repentino",
                    mitigation=MitigationConfig(selected=(name,), anomaly_window_seconds=1),
                )
                result = SimulationEngine(demo_profile(), config).run()
                self.assertTrue(result.samples)
                self.assertTrue(all(sample.users <= config.max_users for sample in result.samples))
                self.assertTrue(all(sample.generated_traffic_mbps >= 0 for sample in result.samples))

    def test_cdn_and_edge_reduce_upstream_traffic(self) -> None:
        config = SimulationConfig(
            initial_users=20,
            max_users=1000,
            duration_seconds=2,
            scenario="Repentino",
            mitigation=MitigationConfig(selected=("CDN / Caching", "Edge / Scrubbing"), cdn_hit_ratio=80, edge_filter_percent=50),
        )
        sample = SimulationEngine(demo_profile(), config).run().samples[-1]
        self.assertLess(sample.traffic_to_origin_mbps, sample.generated_traffic_mbps)
        self.assertGreater(sample.requests_cache, 0)

    def test_autoscaling_increases_model_capacity_once_per_interval(self) -> None:
        config = SimulationConfig(
            initial_users=20,
            max_users=1000,
            duration_seconds=4,
            scenario="Repentino",
            mitigation=MitigationConfig(selected=("Auto Scaling",), autoscaling_max_instances=3, autoscaling_time_seconds=1),
        )
        result = SimulationEngine(demo_profile(), config).run()
        self.assertGreaterEqual(max(sample.instances for sample in result.samples), 2)
        self.assertLessEqual(max(sample.instances for sample in result.samples), 3)


if __name__ == "__main__":
    unittest.main()