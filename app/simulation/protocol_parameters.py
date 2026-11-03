"""Initial calibrated constants specified for the protocol model."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProtocolParameters:
    cpu_seconds_per_request: float = 0.005
    residence_seconds: float = 0.05
    memory_mb_per_connection: float = 0.5
    bits_per_request: float = 160_000
    max_connections_per_thread: int = 256
    requests_per_user_second: float = 0.2
    inertia_seconds: float = 10.0
    noise_sd: float = 0.05
    recovery_confirmation_seconds: int = 10
    recovery_observation_seconds: int = 120
