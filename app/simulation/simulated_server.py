"""Module 3: protocol capacity and state model for the virtual server."""
from __future__ import annotations

from dataclasses import dataclass

from app.models.server_profile import ServerProfile
from app.simulation.protocol_parameters import ProtocolParameters


@dataclass(frozen=True)
class ServerStep:
    utilization: dict[str, float]
    saturation_percent: float
    state: str
    served_rps: float


class SimulatedServer:
    def __init__(self, profile: ServerProfile, parameters: ProtocolParameters) -> None:
        self.parameters = parameters
        self.capacities = self.capacities_for(profile, parameters)
        self.capacity_rps = min(self.capacities.values())
        self.bottleneck = min(self.capacities, key=self.capacities.get)
        self.over_capacity_streak = 0

    @staticmethod
    def capacities_for(profile: ServerProfile, parameters: ProtocolParameters) -> dict[str, float]:
        p = parameters
        threads = max(1, profile.logical_cpus)
        ram_mb = max(1.0, profile.ram_available_mb or profile.ram_total_mb)
        bandwidth_mbps = max(1.0, profile.available_bandwidth_mbps)
        return {
            "CPU": threads / p.cpu_seconds_per_request,
            "RAM": ram_mb / (p.residence_seconds * p.memory_mb_per_connection),
            "Red": bandwidth_mbps * 1_000_000 / p.bits_per_request,
            "Conexiones": (p.max_connections_per_thread * threads) / p.residence_seconds,
        }

    def initial_utilization(self, normal_demand_rps: float) -> dict[str, float]:
        return {key: normal_demand_rps / capacity for key, capacity in self.capacities.items()}

    def projected_saturation(self, demand_rps: float, utilization: dict[str, float]) -> float:
        tau = self.parameters.inertia_seconds
        return max(utilization[key] + (demand_rps / capacity - utilization[key]) / tau
                   for key, capacity in self.capacities.items()) * 100

    def advance(self, demand_rps: float, utilization: dict[str, float],
                capacity_multiplier: float = 1.0) -> ServerStep:
        tau = self.parameters.inertia_seconds
        updated = {
            key: utilization[key] +
            (demand_rps / (capacity * capacity_multiplier) - utilization[key]) / tau
            for key, capacity in self.capacities.items()
        }
        saturation = max(updated.values()) * 100
        self.over_capacity_streak = self.over_capacity_streak + 1 if saturation > 100 else 0
        if saturation > 100 and self.over_capacity_streak >= 10:
            state = "SIMULATED_COLLAPSE"
        elif saturation >= 90 or saturation > 100:
            state = "SATURATION"
        elif saturation >= 70:
            state = "HIGH_LOAD"
        else:
            state = "NORMAL"
        served = min(max(0.0, demand_rps), self.capacity_rps * capacity_multiplier)
        return ServerStep(updated, saturation, state, served)
