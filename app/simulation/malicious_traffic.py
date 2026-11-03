"""Module 2: virtual bot traffic patterns. It never sends network traffic."""
from __future__ import annotations

import random

from app.simulation.experiment_design import SCENARIOS


class MaliciousTraffic:
    def __init__(self, peak_users: int, scenario: str, noise_sd: float = 0.05) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"Escenario malicioso desconocido: {scenario}")
        self.peak_users = peak_users
        self.scenario = scenario
        self.noise_sd = noise_sd

    def users_at(self, attack_second: int, rng: random.Random) -> float:
        if attack_second < 1:
            return 0.0
        if self.scenario == "Gradual":
            shape = attack_second / 120.0
        elif self.scenario == "Súbito":
            shape = 1.0
        elif self.scenario == "Pulsado":
            shape = 1.0 if ((attack_second - 1) // 10) % 2 == 0 else 0.25
        else:  # Spike: brief peak followed by low background bot traffic.
            shape = 1.0 if attack_second <= 10 else 0.25
        multiplier = max(0.85, min(1.15, 1.0 + rng.gauss(0.0, self.noise_sd)))
        return self.peak_users * shape * multiplier
