"""Deterministic, local-only model specified by protocol sections 6 and 7."""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.models.server_profile import ServerProfile
from app.simulation.detection_mitigation import DetectionMitigation
from app.simulation.experiment_design import CONFIRMATION_SECONDS, SCENARIOS, STRATEGIES, USER_LEVELS
from app.simulation.malicious_traffic import MaliciousTraffic
from app.simulation.normal_traffic import NormalTraffic
from app.simulation.protocol_parameters import ProtocolParameters
from app.simulation.simulated_server import SimulatedServer


PHASES = (("NORMAL", 60), ("SIMULATED_ATTACK", 120), ("RECOVERY", 120))


@dataclass
class ProtocolSample:
    second: int
    phase: str
    virtual_users: float
    effective_demand_rps: float
    cpu_percent: float
    ram_percent: float
    network_percent: float
    connections_percent: float
    saturation_percent: float
    served_rps: float
    state: str
    detection_time_s: int | None
    recovery_time_s: int | None
    strategy: str
    bottleneck: str


@dataclass
class ProtocolResult:
    samples: list[ProtocolSample]
    capacity_rps: float
    capacities: dict[str, float]
    bottleneck: str
    detection_time_s: int | None
    recovery_time_s: int | None
    recovery_censored: bool
    max_saturation_percent: float
    max_cpu_percent: float
    max_ram_percent: float
    max_network_percent: float
    max_connections_percent: float
    served_proportion: float
    most_severe_state: str


class ProtocolSimulation:
    """Implements the protocol's 1-second resource model; it performs no I/O."""

    def __init__(self, profile: ServerProfile, peak_users: int, scenario: str,
                 strategy: str, confirmation_seconds: int, seed: int,
                 parameters: ProtocolParameters | None = None, control: bool = False) -> None:
        if scenario not in SCENARIOS or strategy not in STRATEGIES:
            raise ValueError("Escenario o estrategia fuera de los niveles del protocolo.")
        if (peak_users not in USER_LEVELS and peak_users != 0) or confirmation_seconds not in CONFIRMATION_SECONDS:
            raise ValueError("Nivel experimental fuera de los niveles del protocolo.")
        self.profile = profile
        self.peak_users = peak_users
        self.scenario = scenario
        self.strategy = strategy
        self.confirmation_seconds = confirmation_seconds
        self.seed = seed
        self.control = control
        self.p = parameters or ProtocolParameters()
        self.server = SimulatedServer(profile, self.p)
        self.capacities = self.server.capacities
        self.capacity = min(self.capacities.values())
        self.bottleneck = self.server.bottleneck

    def run(self) -> ProtocolResult:
        rng = random.Random(self.seed)
        p = self.p
        normal = NormalTraffic.from_capacity(self.capacity, p.requests_per_user_second)
        malicious = MaliciousTraffic(self.peak_users, self.scenario, p.noise_sd)
        detector = DetectionMitigation(self.strategy, self.confirmation_seconds)
        utilizations = self.server.initial_utilization(normal.demand_rps)
        recovery_streak = 0
        recovery_time = None
        recovery_censored = False
        samples: list[ProtocolSample] = []
        served_total = demand_total = 0.0
        for second in range(1, 301):
            if second <= 60 or (self.control and second <= 180):
                phase, malicious_users = "NORMAL", 0.0
            elif second <= 180:
                phase = "SIMULATED_ATTACK"
                elapsed = second - 60
                malicious_users = malicious.users_at(elapsed, rng)
            else:
                phase, malicious_users = "RECOVERY", 0.0

            demand = p.requests_per_user_second * (normal.users + malicious_users)
            attack_active = phase == "SIMULATED_ATTACK"
            if attack_active:
                projected_saturation = self.server.projected_saturation(demand, utilizations)
                detector.observe(projected_saturation, second - 60)
            mitigation = detector.apply(demand, normal.demand_rps, attack_active)
            server_step = self.server.advance(mitigation.effective_demand_rps, utilizations,
                                              mitigation.capacity_multiplier)
            utilizations = server_step.utilization
            saturation, state = server_step.saturation_percent, server_step.state
            if phase == "RECOVERY":
                if saturation < 70:
                    recovery_streak += 1
                    if recovery_time is None and recovery_streak >= p.recovery_confirmation_seconds:
                        recovery_time = second - 180
                else:
                    recovery_streak = 0
            served = server_step.served_rps
            demand_total += demand
            served_total += served
            reported_phase = detector.phase(attack_active) if attack_active else phase
            samples.append(ProtocolSample(
                second=second, phase=reported_phase, virtual_users=normal.users + malicious_users,
                effective_demand_rps=mitigation.effective_demand_rps,
                cpu_percent=utilizations["CPU"] * 100,
                ram_percent=utilizations["RAM"] * 100,
                network_percent=utilizations["Red"] * 100,
                connections_percent=utilizations["Conexiones"] * 100,
                saturation_percent=saturation, served_rps=served, state=state,
                detection_time_s=detector.detection_time_s, recovery_time_s=recovery_time,
                strategy=mitigation.active_strategy,
                bottleneck=self.bottleneck,
            ))
        if recovery_time is None:
            recovery_censored = True
            recovery_time = p.recovery_observation_seconds
            samples[-1].recovery_time_s = recovery_time
        severity = {"NORMAL": 0, "HIGH_LOAD": 1, "SATURATION": 2, "SIMULATED_COLLAPSE": 3}
        return ProtocolResult(
            samples=samples, capacity_rps=self.capacity, capacities=self.capacities,
            bottleneck=self.bottleneck, detection_time_s=detector.detection_time_s,
            recovery_time_s=recovery_time, recovery_censored=recovery_censored,
            max_saturation_percent=max(s.saturation_percent for s in samples),
            max_cpu_percent=max(s.cpu_percent for s in samples),
            max_ram_percent=max(s.ram_percent for s in samples),
            max_network_percent=max(s.network_percent for s in samples),
            max_connections_percent=max(s.connections_percent for s in samples),
            served_proportion=served_total / demand_total if demand_total else 1.0,
            most_severe_state=max((s.state for s in samples), key=severity.__getitem__),
        )
