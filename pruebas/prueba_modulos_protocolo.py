from __future__ import annotations

import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from aplicacion.ejecutor_experimental import experimental_profiles, run_factorial
from aplicacion.modelos.perfil_servidor import demo_profile
from aplicacion.simulacion.deteccion_mitigacion import DetectionMitigation
from aplicacion.simulacion.trafico_malicioso import MaliciousTraffic
from aplicacion.simulacion.trafico_normal import NormalTraffic
from aplicacion.simulacion.modelo_protocolo import ProtocolSimulation
from aplicacion.simulacion.parametros_protocolo import ProtocolParameters
from aplicacion.simulacion.servidor_simulado import SimulatedServer


class _ZeroNoise:
    @staticmethod
    def gauss(mean: float, sd: float) -> float:
        return 0.0


class ProtocolModuleTests(unittest.TestCase):
    def test_normal_traffic_uses_twenty_percent_capacity_baseline(self) -> None:
        normal = NormalTraffic.from_capacity(1_000)
        self.assertEqual(normal.users, 200)
        self.assertEqual(normal.demand_rps, 40)

    def test_bot_traffic_scenarios_are_separate_and_seedable(self) -> None:
        expected = {
            "Gradual": (60, 50.0),
            "Súbito": (100, 100.0),
            "Pulsado": (11, 25.0),
            "Spike": (11, 25.0),
        }
        for scenario, (second, users) in expected.items():
            with self.subTest(scenario=scenario):
                traffic = MaliciousTraffic(100, scenario)
                self.assertEqual(traffic.users_at(second, _ZeroNoise()), users)

    def test_server_model_emits_protocol_states(self) -> None:
        server = SimulatedServer(demo_profile(), ProtocolParameters())
        utilization = {resource: 1.01 for resource in server.capacities}
        early = server.advance(server.capacity_rps * 1.01, utilization)
        self.assertEqual(early.state, "SATURATION")
        collapse = early
        for _ in range(9):
            collapse = server.advance(server.capacity_rps * 1.01, collapse.utilization)
        self.assertEqual(collapse.state, "SIMULATED_COLLAPSE")

    def test_detection_confirms_consecutive_steps_and_applies_factor(self) -> None:
        detector = DetectionMitigation("Filtrado", 5)
        for second in range(1, 5):
            self.assertIsNone(detector.observe(75, second))
        self.assertEqual(detector.observe(75, 5), 5)
        result = detector.apply(100, 20, in_attack=True)
        self.assertEqual(result.effective_demand_rps, 44)
        self.assertEqual(result.active_strategy, "Filtrado")

    def test_protocol_simulation_is_deterministic_and_has_phases(self) -> None:
        args = (demo_profile(), 5_000, "Gradual", "CAPTCHA", 5, 12345)
        first = ProtocolSimulation(*args).run()
        second = ProtocolSimulation(*args).run()
        self.assertEqual(first.samples, second.samples)
        self.assertEqual(len(first.samples), 300)
        self.assertEqual(first.samples[0].phase, "NORMAL")
        self.assertIn("DETECTION", {sample.phase for sample in first.samples})
        self.assertEqual(first.samples[180].phase, "RECOVERY")

    def test_derived_profile_has_a_distinct_bottleneck(self) -> None:
        profiles = experimental_profiles(demo_profile())
        p = ProtocolParameters()
        p1 = SimulatedServer.capacities_for(profiles["P1"], p)
        p2 = SimulatedServer.capacities_for(profiles["P2"], p)
        self.assertNotEqual(min(p1, key=p1.get), min(p2, key=p2.get))

    def test_single_repetition_factorial_writes_summary_and_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary, trace = run_factorial(demo_profile(), Path(directory), repetitions=1)
            with summary.open(encoding="utf-8-sig", newline="") as handle:
                summary_rows = list(csv.DictReader(handle))
            self.assertEqual(len(summary_rows), 402)
            self.assertEqual(sum(row["scenario"] == "Control" for row in summary_rows), 2)
            with gzip.open(trace, "rt", encoding="utf-8-sig", newline="") as handle:
                trace_reader = csv.DictReader(handle)
                first_row = next(trace_reader)
                self.assertIn("saturation_percent", first_row)


if __name__ == "__main__":
    unittest.main()
