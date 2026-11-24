from __future__ import annotations

from dataclasses import dataclass

from aplicacion.modelos.perfil_servidor import ServerProfile
from aplicacion.modelos.configuracion_simulacion import SimulationConfig


@dataclass
class CapacityEstimate:
    cpu_requests_per_second: float
    memory_users: float
    estimated_users: int
    estimated_requests_per_second: float


class CapacityModel:
    """Local capacity estimate based on CPU, RAM and modeled request rate."""

    def __init__(self, profile: ServerProfile, config: SimulationConfig) -> None:
        self.profile = profile
        self.config = config
        self.service_cpu_factor, self.service_memory_mb_per_user = {
            "Web HTTPS": (1.0, 2.0), "Web HTTP": (0.9, 2.0),
            "API HTTPS": (1.35, 3.0), "Base de datos PostgreSQL": (2.2, 8.0),
            "DNS": (0.35, 0.5), "Personalizado": (1.25, 3.0),
        }.get(config.service_name, (1.25, 3.0))
        self.cpu_capacity = max(profile.logical_cpus, 1) * 180.0 / self.service_cpu_factor
        self.memory_capacity_mb = max(profile.ram_available_mb, profile.ram_total_mb * 0.65, 512.0)

    @property
    def average_request_bytes(self) -> int:
        return {
            "Web HTTPS": 2048, "Web HTTP": 2048, "API HTTPS": 2048,
            "Base de datos PostgreSQL": 1024, "DNS": 128,
        }.get(self.config.service_name, 2048)

    @property
    def average_response_bytes(self) -> int:
        return {
            "Web HTTPS": 16384, "Web HTTP": 16384, "API HTTPS": 8192,
            "Base de datos PostgreSQL": 4096, "DNS": 512,
        }.get(self.config.service_name, 8192)

    def network_consumption_mbps(
        self, inbound_requests_per_second: float, outbound_responses_per_second: float,
        size_factor: float = 1.0,
    ) -> tuple[float, float]:
        """Estimate received/sent traffic; this does not limit server capacity."""
        rx = max(0.0, inbound_requests_per_second) * self.average_request_bytes * size_factor * 8 / 1_000_000
        tx = max(0.0, outbound_responses_per_second) * self.average_response_bytes * size_factor * 8 / 1_000_000
        return rx, tx

    def requests_per_second(self, users: float, requests_per_user: float | None = None) -> float:
        rate = self.config.requests_per_user if requests_per_user is None else requests_per_user
        return max(0.0, users * rate)

    def capacity_for_instances(self, instances: int = 1, capacity_per_instance: float = 0.0) -> float:
        per_instance = capacity_per_instance if capacity_per_instance > 0 else self.cpu_capacity
        return max(0.0, instances * per_instance)

    def resource_usage(
        self,
        effective_users: float,
        processed_requests: float | None = None,
        queued_requests: float = 0.0,
        capacity_multiplier: float = 1.0,
        instances: int = 1,
        waf_cpu_cost: float = 0.0,
    ) -> tuple[float, float, float]:
        requests = self.requests_per_second(effective_users) if processed_requests is None else max(0.0, processed_requests)
        multiplier = max(capacity_multiplier, 1.0)
        cpu = min(
            100.0,
            requests / max(self.capacity_for_instances(instances) * multiplier, 1.0) * 100.0 + waf_cpu_cost,
        )
        memory_mb = max(0.0, effective_users) * self.service_memory_mb_per_user + max(0.0, queued_requests) * 0.25
        ram = min(
            100.0,
            memory_mb / max(self.memory_capacity_mb * multiplier * max(instances, 1), 1.0) * 100.0,
        )
        return cpu, ram, max(cpu, ram)

    def estimate(self) -> CapacityEstimate:
        rate = self.config.requests_per_user
        cpu_percent_per_user = rate / self.cpu_capacity * 100.0
        ram_percent_per_user = self.service_memory_mb_per_user / self.memory_capacity_mb * 100.0
        percent_per_user = max(cpu_percent_per_user, ram_percent_per_user, 0.0001)
        users = max(1, int(70.0 / percent_per_user))
        return CapacityEstimate(
            cpu_requests_per_second=self.cpu_capacity,
            memory_users=self.memory_capacity_mb / self.service_memory_mb_per_user,
            estimated_users=users,
            estimated_requests_per_second=users * rate,
        )

    def summary(self) -> str:
        estimate = self.estimate()
        return (
            "ORIENTACIÓN MATEMÁTICA PARA EL SERVICIO SELECCIONADO\n"
            f"Usuarios antes del umbral: {estimate.estimated_users:,}\n"
            f"Solicitudes máximas estimadas: {estimate.estimated_requests_per_second:,.1f} solicitudes/s\n"
            f"CPU estimada: {estimate.cpu_requests_per_second:,.1f} solicitudes/s\n"
            f"RAM estimada para sesiones: {estimate.memory_users:,.0f} usuarios\n"
            f"Perfil de servicio: {self.config.service_name} (factores educativos no calibrados con benchmark).\n"
            "Estimación basada en CPU y RAM disponible del perfil; no es el máximo real de usuarios ni sustituye una prueba de carga."
        )
