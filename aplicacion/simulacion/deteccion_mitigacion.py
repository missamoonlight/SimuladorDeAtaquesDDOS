"""Module 4: threshold detection and mathematical mitigation effects."""
# CHECK 4/4 — Módulo de detección y mitigación (cronograma: 2–7 nov.).
# La detección confirma umbrales consecutivos y las defensas solo alteran el modelo.
from __future__ import annotations

from dataclasses import dataclass

from aplicacion.simulacion.diseno_experimental import STRATEGIES


MITIGATION_FACTORS = {
    "Ninguna": 1.0,
    "Limitación de tasa": 0.5,
    "Filtrado": 0.3,
    "CAPTCHA": 0.4,
    "Escalamiento": 1.0,
}


@dataclass(frozen=True)
class MitigationStep:
    effective_demand_rps: float
    capacity_multiplier: float
    active_strategy: str


class DetectionMitigation:
    def __init__(self, strategy: str, confirmation_seconds: int) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"Estrategia desconocida: {strategy}")
        if confirmation_seconds not in (5, 20):
            raise ValueError("La confirmación debe ser de 5 o 20 segundos.")
        self.strategy = strategy
        self.confirmation_seconds = confirmation_seconds
        self.consecutive_high = 0
        self.detection_time_s: int | None = None

    def observe(self, projected_saturation_percent: float, attack_second: int) -> int | None:
        if self.detection_time_s is not None:
            return self.detection_time_s
        if projected_saturation_percent >= 70:
            self.consecutive_high += 1
            if self.consecutive_high >= self.confirmation_seconds:
                self.detection_time_s = attack_second
        else:
            self.consecutive_high = 0
        return self.detection_time_s

    def apply(self, demand_rps: float, normal_demand_rps: float,
              in_attack: bool) -> MitigationStep:
        active = in_attack and self.detection_time_s is not None
        if not active:
            return MitigationStep(demand_rps, 1.0, "Ninguna")
        if self.strategy == "Escalamiento":
            return MitigationStep(demand_rps, 2.0, self.strategy)
        factor = MITIGATION_FACTORS[self.strategy]
        effective = normal_demand_rps + (demand_rps - normal_demand_rps) * factor
        return MitigationStep(effective, 1.0, self.strategy)

    def phase(self, in_attack: bool) -> str:
        if not in_attack:
            return ""
        if self.detection_time_s is None and self.consecutive_high:
            return "DETECTION"
        if self.detection_time_s is not None and self.strategy != "Ninguna":
            return "MITIGATION"
        return "SIMULATED_ATTACK"
