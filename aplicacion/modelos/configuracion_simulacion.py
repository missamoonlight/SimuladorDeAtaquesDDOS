from __future__ import annotations

from dataclasses import dataclass, field


MITIGATION_NAMES = (
    "Rate Limiting", "Rate-Based Ban", "Blacklisting", "CAPTCHA / Challenge",
    "WAF / Filtrado L7", "Bot Management", "Auto Scaling", "CDN / Caching",
    "Load Balancing", "Edge / Scrubbing",
)


@dataclass
class MitigationConfig:
    """Parameters for independent local mitigation models."""

    selected: tuple[str, ...] = ("Rate Limiting",)
    rate_limit_rps: float = 500.0
    rate_window_seconds: int = 1
    ban_threshold_rps: float = 800.0
    ban_duration_seconds: int = 10
    ban_evaluations: int = 2
    ban_source_percent: float = 30.0
    blacklist_detect_percent: float = 30.0
    blacklist_block_duration_seconds: int = 30
    blacklist_identification_speed: float = 20.0
    captcha_challenge_percent: float = 40.0
    captcha_solve_probability: float = 75.0
    captcha_delay_ms: float = 80.0
    waf_detection_effectiveness: float = 90.0
    waf_false_positive_rate: float = 2.0
    waf_false_negative_rate: float = 8.0
    waf_cpu_cost_percent: float = 3.0
    waf_latency_ms: float = 12.0
    bot_detection_effectiveness: float = 85.0
    bot_challenge_percent: float = 35.0
    bot_block_percent: float = 40.0
    autoscaling_initial_instances: int = 1
    autoscaling_max_instances: int = 4
    autoscaling_capacity_per_instance_rps: float = 0.0
    autoscaling_time_seconds: int = 5
    autoscaling_cost_cpu_percent: float = 2.0
    cdn_hit_ratio: float = 80.0
    load_balancer_servers: int = 2
    load_balancer_algorithm: str = "Round Robin"
    load_balancer_weights: tuple[float, ...] = (1.0, 1.0)
    edge_filter_capacity_mbps: float = 10000.0
    edge_filter_percent: float = 90.0
    edge_latency_ms: float = 8.0
    anomaly_threshold: float = 70.0
    anomaly_window_seconds: int = 3
    anomaly_sensitivity: float = 1.0
    # Legacy fields retained for compatibility with older saved configurations.
    rate_limiting: float = 35.0
    blacklisting: float = 25.0
    scaling: float = 20.0
    captcha: float = 20.0

    def has(self, name: str) -> bool:
        return name in self.selected

    def validate(self) -> None:
        invalid = set(self.selected) - set(MITIGATION_NAMES)
        if invalid:
            raise ValueError(f"Mitigaciones desconocidas: {', '.join(sorted(invalid))}")
        bounded = {
            "ban_source_percent": self.ban_source_percent,
            "blacklist_detect_percent": self.blacklist_detect_percent,
            "blacklist_identification_speed": self.blacklist_identification_speed,
            "captcha_challenge_percent": self.captcha_challenge_percent,
            "captcha_solve_probability": self.captcha_solve_probability,
            "waf_detection_effectiveness": self.waf_detection_effectiveness,
            "waf_false_positive_rate": self.waf_false_positive_rate,
            "waf_false_negative_rate": self.waf_false_negative_rate,
            "bot_detection_effectiveness": self.bot_detection_effectiveness,
            "bot_challenge_percent": self.bot_challenge_percent,
            "bot_block_percent": self.bot_block_percent,
            "cdn_hit_ratio": self.cdn_hit_ratio,
            "edge_filter_percent": self.edge_filter_percent,
            "anomaly_threshold": self.anomaly_threshold,
            "anomaly_sensitivity": self.anomaly_sensitivity,
        }
        for name, value in bounded.items():
            if not 0 <= value <= 100:
                raise ValueError(f"{name} debe estar entre 0 y 100.")
        if self.rate_limit_rps < 0 or self.ban_threshold_rps < 0 or self.edge_filter_capacity_mbps < 0:
            raise ValueError("Los límites de capacidad no pueden ser negativos.")
        if self.rate_window_seconds <= 0 or self.ban_duration_seconds <= 0 or self.ban_evaluations <= 0:
            raise ValueError("Las ventanas y duraciones deben ser mayores que cero.")
        if self.blacklist_block_duration_seconds <= 0 or self.autoscaling_time_seconds <= 0:
            raise ValueError("Las duraciones de mitigación deben ser mayores que cero.")
        if self.captcha_delay_ms < 0 or self.waf_cpu_cost_percent < 0 or self.waf_latency_ms < 0:
            raise ValueError("Los costes de mitigación no pueden ser negativos.")
        if self.autoscaling_initial_instances < 1 or self.autoscaling_max_instances < self.autoscaling_initial_instances:
            raise ValueError("Las instancias deben cumplir 1 <= inicial <= máximo.")
        if self.load_balancer_servers < 1 or self.load_balancer_algorithm not in {"Round Robin", "Weighted Round Robin", "Least Connections"}:
            raise ValueError("Configuración de balanceo inválida.")


@dataclass
class SimulationConfig:
    initial_users: int = 20
    max_users: int = 1000
    duration_seconds: int = 60
    requests_per_user: float = 1.0
    request_bytes: int = 2048
    response_bytes: int = 16384
    target_latency_ms: float = 200.0
    scenario: str = "Gradual"
    detection_threshold: float = 70.0
    high_load_threshold: float = 50.0
    saturated_threshold: float = 90.0
    sudden_ramp_seconds: int = 5
    seed: int | None = 42
    mitigation_enabled: bool = True
    intensity_base_rps: float = 0.0
    normal_duration_seconds: int = 0
    detection_delay_seconds: int = 0
    bandwidth_mbps: float = 0.0
    mitigation: MitigationConfig = field(default_factory=MitigationConfig)

    def validate(self) -> None:
        if self.initial_users < 0 or self.max_users <= 0 or self.initial_users > self.max_users:
            raise ValueError("Los usuarios deben cumplir 0 <= inicial <= máximo.")
        if self.duration_seconds <= 0 or self.sudden_ramp_seconds <= 0:
            raise ValueError("Las duraciones deben ser mayores que cero.")
        if self.requests_per_user < 0 or self.request_bytes < 0 or self.response_bytes < 0:
            raise ValueError("Requests y bytes no pueden ser negativos.")
        if self.intensity_base_rps < 0 or self.normal_duration_seconds < 0 or self.detection_delay_seconds < 0 or self.bandwidth_mbps < 0:
            raise ValueError("Los parámetros de intensidad, tiempos y ancho de banda no pueden ser negativos.")
        if self.normal_duration_seconds >= self.duration_seconds and self.intensity_base_rps > 0:
            raise ValueError("El inicio del ataque debe ser menor que la duración total.")
        if self.target_latency_ms <= 0:
            raise ValueError("La latencia objetivo debe ser mayor que cero.")
        if not 0 < self.detection_threshold <= 100:
            raise ValueError("El umbral de detección debe estar entre 0 y 100.")
        if not 0 <= self.high_load_threshold < self.detection_threshold < self.saturated_threshold <= 100:
            raise ValueError("Los umbrales deben cumplir carga < detección < saturación.")
        self.mitigation.validate()


def preset(name: str) -> MitigationConfig:
    presets = {
        "Protección básica": ("Rate Limiting",),
        "Protección web": ("WAF / Filtrado L7", "Rate Limiting", "CAPTCHA / Challenge"),
        "Protección avanzada": ("Edge / Scrubbing", "WAF / Filtrado L7", "Bot Management", "Rate Limiting"),
        "Alta disponibilidad": ("Edge / Scrubbing", "CDN / Caching", "Load Balancing", "Auto Scaling"),
        "Defensa multicapa": MITIGATION_NAMES,
    }
    if name not in presets:
        raise ValueError(f"Preset desconocido: {name}")
    return MitigationConfig(selected=tuple(presets[name]))
