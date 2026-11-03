from __future__ import annotations

from dataclasses import dataclass

from aplicacion.modelos.perfil_servidor import ServerProfile
from aplicacion.modelos.configuracion_simulacion import SimulationConfig


@dataclass
class CapacityEstimate:
    cpu_requests_per_second: float
    memory_users: float
    network_requests_per_second: float
    estimated_users: int
    estimated_requests_per_second: float
    estimated_traffic_mbps: float


class CapacityModel:
    """Local capacity abstraction derived from the selected ServerProfile."""

    def __init__(self, profile: ServerProfile, config: SimulationConfig) -> None:
        self.profile = profile
        self.config = config
        self.cpu_capacity = max(profile.logical_cpus, 1) * 180.0
        self.memory_capacity_mb = max(profile.ram_available_mb, profile.ram_total_mb * 0.65, 512.0)
        configured_bandwidth = config.bandwidth_mbps if config.bandwidth_mbps > 0 else profile.available_bandwidth_mbps * 0.72
        self.network_capacity_mbps = max(configured_bandwidth, 10.0)

    @property
    def bytes_per_transaction(self) -> int:
        return self.config.request_bytes + self.config.response_bytes

    def requests_per_second(self, users: float, requests_per_user: float | None = None) -> float:
        rate = self.config.requests_per_user if requests_per_user is None else requests_per_user
        return max(0.0, users * rate)

    def traffic_from_requests(self, requests: float) -> float:
        return max(0.0, requests * self.bytes_per_transaction * 8 / 1_000_000)

    def traffic_mbps(self, users: float, requests_per_user: float | None = None) -> float:
        return self.traffic_from_requests(self.requests_per_second(users, requests_per_user))

    def capacity_for_instances(self, instances: int = 1, capacity_per_instance: float = 0.0) -> float:
        per_instance = capacity_per_instance if capacity_per_instance > 0 else self.cpu_capacity
        return max(0.0, instances * per_instance)

    def resource_usage(
        self,
        effective_users: float,
        processed_requests: float | None = None,
        capacity_multiplier: float = 1.0,
        instances: int = 1,
        waf_cpu_cost: float = 0.0,
    ) -> tuple[float, float, float, float]:
        requests = self.requests_per_second(effective_users) if processed_requests is None else max(0.0, processed_requests)
        traffic = self.traffic_from_requests(requests)
        multiplier = max(capacity_multiplier, 1.0)
        cpu = min(100.0, requests / max(self.capacity_for_instances(instances) * multiplier, 1.0) * 100.0 + waf_cpu_cost)
        memory = min(100.0, max(0.0, effective_users) * 2.0 / max(self.memory_capacity_mb * multiplier * max(instances, 1), 1.0) * 100.0)
        network = min(100.0, traffic / max(self.network_capacity_mbps * multiplier * max(instances, 1), 0.001) * 100.0)
        saturation = min(100.0, max(cpu, memory, network))
        return cpu, memory, network, saturation

    def estimate(self) -> CapacityEstimate:
        per_user = max(
            self.config.requests_per_user / self.cpu_capacity * 100.0,
            2.0 / self.memory_capacity_mb * 100.0,
            self.traffic_mbps(1) / self.network_capacity_mbps * 100.0,
            0.0001,
        )
        users = max(1, int(70.0 / per_user))
        requests = users * self.config.requests_per_user
        return CapacityEstimate(
            cpu_requests_per_second=self.cpu_capacity,
            memory_users=self.memory_capacity_mb / 2.0,
            network_requests_per_second=self.network_capacity_mbps * 1_000_000 / max(self.bytes_per_transaction * 8, 1),
            estimated_users=users,
            estimated_requests_per_second=requests,
            estimated_traffic_mbps=self.traffic_mbps(users),
        )

    def summary(self) -> str:
        estimate = self.estimate()
        return (
            "CAPACIDAD ESTIMADA DEL SERVIDOR\n"
            f"Usuarios antes del umbral: {estimate.estimated_users:,}\n"
            f"Requests máximas estimadas: {estimate.estimated_requests_per_second:,.1f} req/s\n"
            f"Tráfico máximo estimado: {estimate.estimated_traffic_mbps:,.2f} Mbps\n"
            "\nEsta capacidad es una estimación matemática y no sustituye una prueba de carga controlada."
        )
