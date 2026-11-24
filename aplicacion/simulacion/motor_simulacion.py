from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field, replace

from aplicacion.modelos.perfil_servidor import ServerProfile
from aplicacion.modelos.configuracion_simulacion import SimulationConfig
from aplicacion.simulacion.modelo_capacidad import CapacityModel


SATURATION_STABLE_LIMIT = 50.0
SATURATION_NEAR_LIMIT = 75.0
SATURATION_CRITICAL_LIMIT = 90.0


@dataclass
class SimulationSample:
    second: int
    users: int
    effective_users: int
    generated_requests_s: float
    processed_requests_s: float
    requests_s: float
    cpu_percent: float
    ram_percent: float
    saturation_percent: float
    latency_ms: float
    state: str
    network_rx_mbps: float = 0.0
    network_tx_mbps: float = 0.0
    legitimate_requests_s: float = 0.0
    malicious_requests_s: float = 0.0
    users_generated: int = 0
    users_legitimate: int = 0
    users_suspicious: int = 0
    users_blocked: int = 0
    requests_generated: float = 0.0
    requests_queued: float = 0.0
    requests_dropped: float = 0.0
    requests_limited: float = 0.0
    requests_blocked: float = 0.0
    requests_challenge: float = 0.0
    requests_cache: float = 0.0
    requests_origin: float = 0.0
    legitimate_preserved: float = 0.0
    false_positive_requests: float = 0.0
    instances: int = 1
    capacity_rps: float = 0.0
    sources_detected: int = 0
    sources_blocked: int = 0
    mitigation_active: str = "Ninguna"
    anomaly_score: float = 0.0
    server_loads: tuple[float, ...] = ()
    # Per-second virtual bot activity; these are model entities, never OS processes.
    malicious_bot_activity: tuple[tuple[int, int], ...] = ()


@dataclass
class ClientHourSummary:
    hour_index: int
    simulation_day: int
    hour_of_day: int
    period_start_second: int
    period_end_second: int
    client_id: str
    source_ip: str
    source_port: int | str
    traffic_class: str
    service_name: str
    service_port: int
    service_protocol: str
    requests: int
    estimated_inbound_requests: float
    estimated_responses: float
    inbound_bytes: int
    outbound_bytes: int
    granularity: str = "Individual"
    source_detected: bool = False
    source_blocked: bool = False

    @property
    def inbound_average_mbps(self) -> float:
        elapsed = max(1, self.period_end_second - self.period_start_second + 1)
        return self.inbound_bytes * 8 / elapsed / 1_000_000

    @property
    def outbound_average_mbps(self) -> float:
        elapsed = max(1, self.period_end_second - self.period_start_second + 1)
        return self.outbound_bytes * 8 / elapsed / 1_000_000

@dataclass
class SimulationResult:
    samples: list[SimulationSample] = field(default_factory=list)
    client_hourly: list[ClientHourSummary] = field(default_factory=list)
    detected_at: int | None = None
    mitigation_at: int | None = None
    recovery_at: int | None = None
    max_saturation: float = 0.0
    time_saturated: int = 0
    sources_detected: int = 0
    sources_blocked: int = 0

    @property
    def dropped_requests(self) -> float:
        return sum(sample.requests_dropped for sample in self.samples)

    @property
    def capacity_conclusion(self) -> str:
        """Plain-language assessment for this simulated attack scenario."""
        if not self.samples:
            return "No hay datos suficientes para evaluar el servidor."
        saturation = self.max_saturation
        if saturation < SATURATION_STABLE_LIMIT:
            if self.dropped_requests > 0:
                return (
                    "Recursos estables, pero se rechazaron "
                    f"{self.dropped_requests:,.0f} solicitudes; revisa la cola antes de considerarlo apto."
                )
            return "Servidor estable y apto para este escenario simulado."
        if saturation < SATURATION_NEAR_LIMIT:
            return "Carga alta; el servidor conserva margen de recursos en este escenario."
        if saturation < SATURATION_CRITICAL_LIMIT:
            return "Servidor cerca del límite; un aumento del tráfico podría generar cola."
        if self.dropped_requests > 0:
            return (
                "Servidor sobresaturado y no apto para este escenario: "
                f"alcanzó {saturation:.1f}% y rechazó {self.dropped_requests:,.0f} solicitudes."
            )
        if saturation >= 100:
            return "Servidor alcanzó el límite modelado, aunque no se registraron rechazos por cola."
        return "Servidor en sobrecarga crítica; aún no registró rechazos por cola, pero tiene poco margen."

    @property
    def detection_time(self) -> int | None:
        return self.detected_at

    @property
    def mitigation_time(self) -> int | None:
        return self.mitigation_at

    @property
    def request_reduction_percent(self) -> float:
        generated = sum(item.requests_generated for item in self.samples)
        processed = sum(item.processed_requests_s for item in self.samples)
        return max(0.0, (1.0 - processed / generated) * 100.0) if generated else 0.0

    @property
    def origin_load_reduction_percent(self) -> float:
        return self.request_reduction_percent

    @property
    def legitimate_traffic_preserved(self) -> float:
        return sum(item.legitimate_preserved for item in self.samples)

    @property
    def false_positive_rate(self) -> float:
        legitimate = sum(item.legitimate_requests_s for item in self.samples)
        false_positives = sum(item.false_positive_requests for item in self.samples)
        return false_positives / max(legitimate, 1.0) * 100.0

    @property
    def mitigation_efficiency(self) -> float:
        return self.request_reduction_percent


@dataclass
class ComparisonRow:
    name: str
    max_saturation: float
    max_cpu: float
    max_ram: float
    max_latency: float
    requests_blocked: float
    recovery_time: int | None


class SimulationEngine:
    """Runs a deterministic local-only mitigation pipeline; it never performs network I/O."""

    def __init__(self, profile: ServerProfile, config: SimulationConfig, *, fast_forward: bool = False) -> None:
        config.validate()
        if config.seed is None:
            config.seed = random.SystemRandom().randrange(0, 2**32)
        self.profile = profile
        self.config = config
        self.fast_forward = fast_forward
        self.model = CapacityModel(profile, config)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()
        self._ban_remaining = 0
        self._ban_streak = 0
        self._blacklist_block_percent = 0.0
        self._blacklist_ttl = 0
        self._instances = config.mitigation.autoscaling_initial_instances
        self._autoscaling_pending: list[int] = []
        self._autoscaling_last_action = -10_000
        self._autoscaling_low_load_streak = 0
        self._legitimate_users_current = config.initial_users
        self._request_queue_depth = 0.0

    def stop(self) -> None:
        self._stop.set()
        self._pause.set()

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def run(self, on_sample=None, on_event=None) -> SimulationResult:
        rng = random.Random(self.config.seed)
        self.model = CapacityModel(self.profile, self.config)
        variation = self.config.random_variation_percent / 100.0
        if variation:
            center = self.config.duration_seconds * 0.15
            spread = self.config.duration_seconds * variation
            lower_start = max(0, round(center - spread))
            upper_start = min(max(0, self.config.duration_seconds - 1), round(center + spread))
            self._attack_start_seconds = rng.randint(lower_start, upper_start)
            self._sudden_ramp_seconds = self._random_sudden_ramp(rng) if self.config.scenario == "Repentino" else 1
        else:
            self._attack_start_seconds = max(self.config.normal_duration_seconds, round(self.config.duration_seconds * 0.15))
            self._sudden_ramp_seconds = self._random_sudden_ramp(rng) if self.config.scenario == "Repentino" else 1
        self._current_second = 0
        self._legitimate_users_current = self.config.initial_users
        self._request_queue_depth = 0.0
        self._ban_remaining = 0
        self._ban_streak = 0
        self._blacklist_block_percent = 0.0
        self._blacklist_ttl = 0
        self._instances = self.config.mitigation.autoscaling_initial_instances if self.config.mitigation.has("Auto Scaling") else 1
        self._autoscaling_pending = []
        self._autoscaling_last_action = -10_000
        self._autoscaling_low_load_streak = 0
        self._detection_processing_delay = rng.randint(1, 5)
        detection_ready_at = None
        result = SimulationResult()
        client_hourly: dict[tuple[int, str, int], dict[str, object]] = {}
        client_source_ports: dict[tuple[str, int], int] = {}
        detected = False
        mitigated = False
        anomaly_streak = 0
        for second in range(1, self.config.duration_seconds + 1):
            if self._stop.is_set():
                break
            self._pause.wait()
            if self.config.real_time and not self._wait_real_second():
                break
            self._current_second = second
            generated_users = self._users_at(second, rng)
            users_legitimate = self._legitimate_users_current
            users_suspicious = max(0, generated_users - users_legitimate)
            traffic_size_factor = self._variation_factor(rng)
            per_second_client_requests: list[tuple[str, int, int]] = []
            legitimate_requests, malicious_requests = self._request_components(
                generated_users, rng, legitimate_users=users_legitimate,
                on_client_requests=lambda kind, client_index, requests: per_second_client_requests.append((kind, client_index, requests)),
            )
            generated_requests = legitimate_requests + malicious_requests
            expected_legitimate = max(self._expected_legitimate_requests(users_legitimate), 1.0)
            # An expected legitimate peak can raise resource load without being
            # misclassified as an attack. The model scores the malicious component.
            anomaly_score = min(100.0, malicious_requests / expected_legitimate * 45.0 * self.config.mitigation.anomaly_sensitivity)
            detection_window_open = second > self._attack_start_seconds
            if detection_window_open and anomaly_score >= self.config.mitigation.anomaly_threshold:
                anomaly_streak += 1
            else:
                anomaly_streak = 0
            if not detected and detection_ready_at is None and anomaly_streak >= self.config.mitigation.anomaly_window_seconds:
                detection_ready_at = second + self._detection_processing_delay
            if not detected and detection_ready_at is not None and second >= detection_ready_at:
                detected = True
                result.detected_at = second
                if on_event:
                    on_event(f"Anomalia detectada en t={second}s tras confirmar el patron y una demora interna variable.")
            metrics = self._pipeline(
                second, generated_users, generated_requests, legitimate_requests, malicious_requests,
                users_legitimate, users_suspicious, detected, rng, traffic_size_factor, on_event,
                per_second_client_requests,
            )
            served_response_ratio = min(1.0, metrics["processed_requests"] / max(generated_requests, 1.0))
            received_request_ratio = min(1.0, metrics["network_rx_requests"] / max(generated_requests, 1.0))
            for kind, client_index, requests in per_second_client_requests:
                if requests <= 0:
                    continue
                hour_index = (second - 1) // 3600
                key = (hour_index, kind, client_index)
                source_key = (kind, client_index)
                if source_key not in client_source_ports:
                    client_source_ports[source_key] = rng.randint(49152, 65535)
                source_port = client_source_ports[source_key]
                row = client_hourly.setdefault(key, {
                    "requests": 0, "inbound_requests": 0.0, "responses": 0.0,
                    "inbound_bytes": 0, "outbound_bytes": 0,
                    "source_port": source_port,
                })
                row["requests"] += requests
                estimated_inbound = requests * received_request_ratio
                estimated_responses = requests * served_response_ratio
                row["inbound_requests"] += estimated_inbound
                row["responses"] += requests * served_response_ratio
                row["inbound_bytes"] += round(estimated_inbound * self.model.average_request_bytes * traffic_size_factor)
                row["outbound_bytes"] += round(estimated_responses * self.model.average_response_bytes * traffic_size_factor)
                source_detected = kind == "Malicioso" and detected and metrics["sources_detected"] > 0 and (
                    client_index == 0 or client_index <= metrics["sources_detected"]
                )
                source_blocked = source_detected and metrics["sources_blocked"] > 0 and (
                    client_index == 0 or client_index <= metrics["sources_blocked"]
                )
                row["detected"] = bool(row.get("detected", False) or source_detected)
                row["blocked"] = bool(row.get("blocked", False) or source_blocked)
            if detected and self.config.mitigation_enabled and self.config.mitigation.selected and not mitigated:
                mitigated = True
                result.mitigation_at = second
                if on_event:
                    on_event("Anomalía confirmada; las capas seleccionadas siguen actuando y el blacklist puede iniciar la identificación de fuentes.")
            if metrics["saturation"] < self.config.high_load_threshold and mitigated and result.recovery_at is None:
                result.recovery_at = second
                if on_event:
                    on_event("Servidor recuperado dentro del modelo.")
            active = ", ".join(self.config.mitigation.selected) if self.config.mitigation_enabled else "Ninguna"
            sample = SimulationSample(
                second=second, users=generated_users, effective_users=int(metrics["effective_users"]),
                generated_requests_s=generated_requests, processed_requests_s=metrics["processed_requests"],
                legitimate_requests_s=legitimate_requests, malicious_requests_s=malicious_requests,
                requests_s=metrics["processed_requests"],
                network_rx_mbps=metrics["network_rx_mbps"], network_tx_mbps=metrics["network_tx_mbps"],
                cpu_percent=metrics["cpu"], ram_percent=metrics["ram"], saturation_percent=metrics["saturation"],
                latency_ms=metrics["latency"], state=self._state(metrics["saturation"], detected, mitigated),
                users_generated=generated_users, users_legitimate=users_legitimate,
                users_suspicious=users_suspicious, users_blocked=metrics["users_blocked"],
                requests_generated=generated_requests, requests_limited=metrics["requests_limited"],
                requests_queued=metrics["requests_queued"], requests_dropped=metrics["requests_dropped"],
                requests_blocked=metrics["requests_blocked"], requests_challenge=metrics["requests_challenge"],
                requests_cache=metrics["requests_cache"], requests_origin=metrics["requests_origin"],
                legitimate_preserved=metrics["legitimate_preserved"],
                false_positive_requests=metrics["false_positives"], instances=metrics["instances"],
                capacity_rps=metrics["capacity_rps"], sources_detected=metrics["sources_detected"],
                sources_blocked=metrics["sources_blocked"], mitigation_active=active, anomaly_score=anomaly_score,
                server_loads=metrics["server_loads"],
                malicious_bot_activity=tuple(
                    (client_index, requests)
                    for kind, client_index, requests in per_second_client_requests
                    if kind == "Malicioso" and requests > 0
                ),
            )
            assert generated_users <= self.config.max_users
            self._assert_sample(sample)
            result.samples.append(sample)
            result.max_saturation = max(result.max_saturation, sample.saturation_percent)
            result.time_saturated += int(sample.saturation_percent >= self.config.saturated_threshold)
            result.sources_detected = max(result.sources_detected, sample.sources_detected)
            result.sources_blocked = max(result.sources_blocked, sample.sources_blocked)
            if on_sample:
                on_sample(sample)
            if not self.config.real_time and not self.fast_forward:
                time.sleep(0.04)
        elapsed = len(result.samples)
        for (hour_index, kind, client_index), row in sorted(client_hourly.items()):
            period_start = hour_index * 3600 + 1
            period_end = min(elapsed, (hour_index + 1) * 3600)
            is_group = client_index == 0
            client_id = f"{kind}-AGREGADO" if is_group else f"{kind}-{client_index:06d}"
            source_ip = "Agregado" if is_group else self._synthetic_client_ip(kind, client_index)
            result.client_hourly.append(ClientHourSummary(
                hour_index=hour_index + 1,
                simulation_day=(self.config.start_hour + hour_index) // 24 + 1,
                hour_of_day=(self.config.start_hour + hour_index) % 24,
                period_start_second=period_start,
                period_end_second=period_end, client_id=client_id, source_ip=source_ip,
                source_port=row["source_port"] if not is_group else "N/D", traffic_class=kind,
                service_name=self.config.service_name, service_port=self.config.service_port,
                service_protocol=self.config.service_protocol,
                requests=int(row["requests"]), estimated_inbound_requests=float(row["inbound_requests"]),
                estimated_responses=float(row["responses"]), inbound_bytes=int(row["inbound_bytes"]),
                outbound_bytes=int(row["outbound_bytes"]),
                granularity="Grupo agregado" if is_group else "Individual",
                source_detected=bool(row.get("detected", False)),
                source_blocked=bool(row.get("blocked", False)),
            ))
        return result

    @staticmethod
    def _synthetic_client_ip(kind: str, index: int) -> str:
        """Return a private, non-routable address used only as simulated identity."""
        base_second_octet = 240 if kind == "Legítimo" else 241
        offset = max(0, index - 1)
        third = (offset // 254) % 256
        fourth = offset % 254 + 1
        return f"10.{base_second_octet}.{third}.{fourth}"

    def _wait_real_second(self) -> bool:
        """Wait one active wall-clock second, excluding time spent paused."""
        remaining = 1.0
        while remaining > 0:
            if self._stop.is_set():
                return False
            if not self._pause.is_set():
                while not self._pause.wait(0.05):
                    if self._stop.is_set():
                        return False
                continue
            interval = min(remaining, 0.05)
            started = time.monotonic()
            if self._stop.wait(interval):
                return False
            if self._pause.is_set():
                remaining -= time.monotonic() - started
        return not self._stop.is_set()

    def _pipeline(
        self, second, users, generated, legitimate, malicious, users_legitimate,
        users_suspicious, detected, rng, traffic_size_factor, on_event, client_requests,
    ):
        mitigation = self.config.mitigation
        if not self.config.mitigation_enabled:
            mitigation = replace(mitigation, selected=())
        elif not detected:
            # Preventive layers (edge filtering, rate rules, WAF, bot
            # screening, challenges, cache, LB and scaling) can operate
            # before a global alert. Blacklisting needs confirmed sources.
            selected = tuple(name for name in mitigation.selected if name != "Blacklisting")
            mitigation = replace(mitigation, selected=selected)

        legitimate_left = max(0.0, legitimate)
        malicious_left = max(0.0, malicious)
        malicious_blocked = 0.0
        blocked_source_percent = 0.0
        false_positives = 0.0
        challenge = 0.0
        challenge_block = 0.0
        rate_limited = 0.0
        edge_latency = 0.0
        waf_latency = 0.0

        # L3/L4 scrubbing belongs at the network edge: it drops attack traffic
        # before the protected application, while preserving modeled clients.
        if mitigation.has("Edge / Scrubbing"):
            edge_latency = mitigation.edge_latency_ms
            edge_block = malicious_left * mitigation.edge_filter_percent / 100.0
            malicious_left -= edge_block
            malicious_blocked += edge_block

        # Rate-based bans and IP blacklists operate on sources, so estimate
        # their effect over the malicious source pool rather than all requests.
        malicious_source_rate = malicious / max(users_suspicious, 1)
        if mitigation.has("Rate-Based Ban") and malicious_source_rate >= mitigation.ban_threshold_rps:
            self._ban_streak += 1
            if self._ban_streak >= mitigation.ban_evaluations:
                self._ban_remaining = mitigation.ban_duration_seconds
        else:
            self._ban_streak = 0
        if self._ban_remaining > 0:
            ban_block = malicious_left * mitigation.ban_source_percent / 100.0
            malicious_left -= ban_block
            malicious_blocked += ban_block
            blocked_source_percent = mitigation.ban_source_percent
            self._ban_remaining -= 1

        if mitigation.has("Blacklisting") and detected and malicious_left > 0:
            self._blacklist_block_percent = min(
                mitigation.blacklist_detect_percent,
                self._blacklist_block_percent + mitigation.blacklist_identification_speed,
            )
            self._blacklist_ttl = mitigation.blacklist_block_duration_seconds
        elif self._blacklist_ttl > 0:
            self._blacklist_ttl -= 1
        else:
            self._blacklist_block_percent = 0.0
        if mitigation.has("Blacklisting") and self._blacklist_ttl > 0:
            blacklist_block = malicious_left * self._blacklist_block_percent / 100.0
            malicious_left -= blacklist_block
            malicious_blocked += blacklist_block
            blocked_source_percent = 100.0 - (
                (1.0 - blocked_source_percent / 100.0)
                * (1.0 - self._blacklist_block_percent / 100.0)
            ) * 100.0

        # Rate limiting is modeled per source, not as one global server cap.
        # Legitimate requests get their own per-client allowance; excess
        # requests are throttled before they enter the origin queue.
        if mitigation.has("Rate Limiting"):
            per_source_limit = mitigation.rate_limit_rps
            legitimate_ratio = legitimate_left / max(legitimate, 1.0)
            malicious_ratio = malicious_left / max(malicious, 1.0)
            legitimate_admitted = 0.0
            malicious_admitted = 0.0
            if client_requests:
                for kind, client_index, requests in client_requests:
                    is_malicious = kind == "Malicioso"
                    class_ratio = malicious_ratio if is_malicious else legitimate_ratio
                    after_prior_layers = requests * class_ratio
                    source_count = users_suspicious if is_malicious else users_legitimate
                    allowance = (
                        source_count * per_source_limit if client_index == 0
                        else per_source_limit
                    )
                    admitted = min(after_prior_layers, allowance)
                    if is_malicious:
                        malicious_admitted += admitted
                    else:
                        legitimate_admitted += admitted
            else:
                legitimate_admitted = min(legitimate_left, users_legitimate * per_source_limit)
                malicious_admitted = min(malicious_left, users_suspicious * per_source_limit)
            legitimate_limited = legitimate_left - legitimate_admitted
            malicious_limited = malicious_left - malicious_admitted
            rate_limited = legitimate_limited + malicious_limited
            legitimate_left = legitimate_admitted
            malicious_left = malicious_admitted

        # WAF rules inspect application requests and may block attack patterns;
        # false positives are charged only to legitimate traffic.
        waf_inspected = legitimate_left + malicious_left if mitigation.has("WAF / Filtrado L7") else 0.0
        if mitigation.has("WAF / Filtrado L7"):
            waf_block_ratio = mitigation.waf_detection_effectiveness * (100.0 - mitigation.waf_false_negative_rate) / 10_000.0
            waf_block = malicious_left * waf_block_ratio
            malicious_left -= waf_block
            malicious_blocked += waf_block
            false_positives = legitimate_left * mitigation.waf_false_positive_rate / 100.0
            legitimate_left -= false_positives
            waf_latency = mitigation.waf_latency_ms

        # Bot management first classifies, then blocks a portion and challenges
        # a distinct portion of the remaining suspicious traffic.
        if mitigation.has("Bot Management"):
            classified = malicious_left * mitigation.bot_detection_effectiveness / 100.0
            bot_block = classified * mitigation.bot_block_percent / 100.0
            malicious_left -= bot_block
            malicious_blocked += bot_block
            challenge = min(malicious_left, (classified - bot_block) * mitigation.bot_challenge_percent / 100.0)
            malicious_left -= challenge
            bot_passed = challenge * mitigation.captcha_solve_probability / 100.0
            bot_failed = challenge - bot_passed
            challenge_block += bot_failed
            malicious_blocked += bot_failed
            malicious_left += bot_passed

        # CAPTCHA is a separate challenge layer. Since this synthetic attack
        # population represents bots, only a small configured share passes.
        if mitigation.has("CAPTCHA / Challenge"):
            captcha_challenge = malicious_left * mitigation.captcha_challenge_percent / 100.0
            malicious_left -= captcha_challenge
            challenge += captcha_challenge
            passed = captcha_challenge * mitigation.captcha_solve_probability / 100.0
            challenge_block += captcha_challenge - passed
            malicious_blocked += captcha_challenge - passed
            malicious_left += passed

        source_identification = [50.0]
        if mitigation.has("WAF / Filtrado L7"):
            source_identification.append(mitigation.waf_detection_effectiveness)
        if mitigation.has("Bot Management"):
            source_identification.append(mitigation.bot_detection_effectiveness)
        if mitigation.has("Blacklisting"):
            source_identification.append(mitigation.blacklist_detect_percent)
        if mitigation.has("Edge / Scrubbing"):
            source_identification.append(mitigation.edge_filter_percent)
        detected_sources = round(users_suspicious * max(source_identification) / 100.0) if detected else 0

        # A CDN only serves cacheable assets. Dynamic/API/database attack
        # requests are treated as cache misses; benign web assets are more
        # likely to be cached. This is a service-level approximation.
        cacheable_legitimate = {
            "Web HTTPS": 0.65, "Web HTTP": 0.65, "API HTTPS": 0.15,
            "Base de datos PostgreSQL": 0.0, "DNS": 0.80,
        }.get(self.config.service_name, 0.30)
        cacheable_malicious = (
            0.05 if self.config.service_name.startswith("Web")
            else 0.10 if self.config.service_name == "DNS"
            else 0.0
        )
        cache = 0.0
        cached_legitimate = 0.0
        if mitigation.has("CDN / Caching"):
            hit_ratio = mitigation.cdn_hit_ratio / 100.0
            cached_legitimate = legitimate_left * cacheable_legitimate * hit_ratio
            cache = cached_legitimate
            cache += malicious_left * cacheable_malicious * hit_ratio
            legitimate_left *= 1.0 - cacheable_legitimate * hit_ratio
            malicious_left *= 1.0 - cacheable_malicious * hit_ratio

        candidate = max(0.0, legitimate_left + malicious_left)
        processed_before_lb = candidate
        limited = rate_limited
        server_count = mitigation.load_balancer_servers if mitigation.has("Load Balancing") else 1
        per_instance_capacity = mitigation.autoscaling_capacity_per_instance_rps or self.model.estimate().estimated_requests_per_second
        instances = self._update_autoscaling(
            second, processed_before_lb / server_count, per_instance_capacity,
            self._request_queue_depth,
        )
        capacity = self.model.capacity_for_instances(instances * server_count, per_instance_capacity)
        queued_total = self._request_queue_depth + processed_before_lb
        processed = min(queued_total, capacity)
        queue_limit = max(1.0, capacity * 2.0)
        queue_remaining = max(0.0, queued_total - processed)
        dropped = max(0.0, queue_remaining - queue_limit)
        self._request_queue_depth = min(queue_limit, queue_remaining)
        if server_count > 1:
            if mitigation.load_balancer_algorithm == "Weighted Round Robin":
                weights = list(mitigation.load_balancer_weights[:server_count])
                weights += [1.0] * (server_count - len(weights))
                total_weight = sum(weights) or 1.0
                loads = tuple(min(100.0, processed * weight / total_weight / max(per_instance_capacity * instances, 1.0) * 100.0) for weight in weights)
            else:
                loads = tuple(min(100.0, processed / server_count / max(per_instance_capacity * instances, 1.0) * 100.0) for _ in range(server_count))
        else:
            loads = (min(100.0, processed / max(per_instance_capacity * instances, 1.0) * 100.0),)
        # Keep security blocks, rate-limited requests, queue drops and cache
        # hits as separate counters so the dashboard does not double-count them.
        requests_blocked = malicious_blocked + false_positives
        # Only clients whose traffic survives mitigation are counted as active
        # sessions on the protected server. Requests filtered upstream (edge,
        # WAF, bot controls, rate limit) must not keep inflating server RAM.
        admitted_ratio = min(1.0, processed_before_lb / max(generated, 1.0))
        effective_users = max(0.0, users * admitted_ratio)
        blocked_users = min(users_suspicious, round(users_suspicious * blocked_source_percent / 100.0))
        waf_cost = mitigation.waf_cpu_cost_percent * min(1.0, waf_inspected / max(capacity, 1.0))
        cpu, ram, saturation = self.model.resource_usage(
            effective_users, processed, queued_requests=self._request_queue_depth,
            instances=instances * server_count, waf_cpu_cost=waf_cost,
        )
        delay = edge_latency + waf_latency + (challenge * mitigation.captcha_delay_ms / max(generated, 1.0))
        queue_delay_ms = self._request_queue_depth / max(capacity, 1.0) * 1000.0
        latency = self.config.target_latency_ms * (1.0 + saturation / 100.0) + delay + queue_delay_ms + rng.uniform(-3.0, 3.0)
        network_rx, network_tx = self.model.network_consumption_mbps(
            processed_before_lb, processed, traffic_size_factor,
        )
        return {"effective_users": effective_users, "processed_requests": processed,
                "requests_limited": limited, "requests_blocked": requests_blocked,
                "requests_queued": self._request_queue_depth, "requests_dropped": dropped,
                "requests_challenge": challenge, "requests_cache": cache,
                "requests_origin": processed, "users_blocked": blocked_users,
                "legitimate_preserved": max(0.0, legitimate_left + cached_legitimate),
                "false_positives": false_positives, "instances": instances,
                "capacity_rps": capacity, "sources_detected": detected_sources,
                "sources_blocked": blocked_users, "server_loads": loads,
                "network_rx_requests": processed_before_lb,
                "network_rx_mbps": network_rx, "network_tx_mbps": network_tx,
                "cpu": cpu, "ram": ram, "saturation": max(0.0, min(100.0, saturation)),
                "latency": max(0.0, latency)}
    def _update_autoscaling(
        self, second: int, incoming: float, per_instance_capacity: float | None = None,
        queued_requests: float = 0.0,
    ) -> int:
        mitigation = self.config.mitigation
        if not mitigation.has("Auto Scaling"):
            return 1
        per_instance = per_instance_capacity or mitigation.autoscaling_capacity_per_instance_rps or self.model.cpu_capacity
        interval = max(1, mitigation.autoscaling_time_seconds)
        ready = sum(ready_at <= second for ready_at in self._autoscaling_pending)
        if ready:
            self._instances = min(mitigation.autoscaling_max_instances, self._instances + ready)
            self._autoscaling_pending = [ready_at for ready_at in self._autoscaling_pending if ready_at > second]

        current_capacity = max(1.0, self._instances * per_instance)
        pending_count = len(self._autoscaling_pending)
        if incoming > current_capacity * 0.70 and self._instances + pending_count < mitigation.autoscaling_max_instances:
            self._autoscaling_low_load_streak = 0
            if second - self._autoscaling_last_action >= interval:
                # New capacity becomes available only after a modeled warm-up.
                self._autoscaling_pending.append(second + max(2, interval))
                self._autoscaling_last_action = second
        elif incoming + queued_requests < current_capacity * 0.30 and queued_requests <= 0:
            self._autoscaling_low_load_streak += 1
            if (
                self._instances > mitigation.autoscaling_initial_instances
                and self._autoscaling_low_load_streak >= interval * 3
                and second - self._autoscaling_last_action >= interval
            ):
                self._instances -= 1
                self._autoscaling_last_action = second
                self._autoscaling_low_load_streak = 0
        else:
            self._autoscaling_low_load_streak = 0
        return self._instances

    def _random_sudden_ramp(self, rng: random.Random) -> int:
        upper_seconds = max(1, min(10, round(self.config.duration_seconds * 0.2)))
        return rng.randint(1, upper_seconds)

    def _attack_progress_at(self, second: int) -> float:
        elapsed = second - getattr(self, "_attack_start_seconds", 0)
        if elapsed <= 0:
            return 0.0
        duration = max(1, self.config.duration_seconds - getattr(self, "_attack_start_seconds", 0))
        scenario = self.config.scenario
        if scenario == "Repentino":
            return min(1.0, elapsed / max(1, min(getattr(self, "_sudden_ramp_seconds", 1), duration)))
        if scenario == "Pulsante":
            phase = (elapsed - 1) % 20
            pulse = max(0.0, math.sin(math.pi * phase / 10.0))
            return 0.08 + 0.92 * pulse ** 2
        if scenario == "Spike":
            center = max(1.0, min(4.0, duration * 0.12))
            width = max(1.5, min(3.0, duration * 0.08))
            return math.exp(-0.5 * ((elapsed - center) / width) ** 2)
        progress = min(1.0, elapsed / duration)
        if scenario == "Gradual":
            return progress * progress * (3.0 - 2.0 * progress)
        return progress

    def _users_at(self, second: int, rng: random.Random | None = None) -> int:
        baseline_users = self.config.initial_users * self._legitimate_demand_factor(second)
        if rng is not None and baseline_users > 0:
            # Resample around the initial cohort each second, so the count can rise
            # or fall without inheriting a random-walk trend from the previous tick.
            fluctuation = max(1, round(baseline_users * 0.10))
            standard_deviation = max(0.5, fluctuation / 2.0)
            lower = max(0, round(baseline_users - fluctuation))
            upper = min(self.config.max_users, round(baseline_users + fluctuation))
            self._legitimate_users_current = round(
                min(upper, max(lower, rng.gauss(baseline_users, standard_deviation)))
            )
        else:
            self._legitimate_users_current = min(self.config.max_users, round(baseline_users))
        attack_capacity = max(0, self.config.max_users - self._legitimate_users_current)
        attack_users = round(attack_capacity * self._attack_progress_at(second))
        if attack_users and rng and self.config.random_variation_percent:
            attack_users = round(attack_users * self._variation_factor(rng))
        return min(self.config.max_users, self._legitimate_users_current + max(0, attack_users))

    def _legitimate_demand_factor(self, second: int) -> float:
        profile = self.config.legitimate_profile
        if profile == "Variación normal":
            return 1.0
        if profile == "Hora pico":
            hour = (self.config.start_hour + second / 3600.0) % 24
            distance = min((hour - 13) % 24, (13 - hour) % 24)
            return 1.0 + 0.65 * math.exp(-0.5 * (distance / 1.0) ** 2)
        progress = second / max(1, self.config.duration_seconds)
        distance = (progress - 0.5) / 0.18
        return 1.0 + 1.4 * math.exp(-0.5 * distance * distance)

    def _expected_legitimate_requests(self, users: int) -> float:
        low_rate, high_rate = self._service_request_rate_range()
        expected_per_user = (low_rate + high_rate) / 2.0
        return max(1.0, users * expected_per_user)

    def _request_components(
        self, users: int, rng: random.Random | None = None, legitimate_users: int | None = None,
        on_client_requests=None,
    ) -> tuple[float, float]:
        legitimate_users = min(users, self.config.initial_users) if legitimate_users is None else min(users, legitimate_users)
        attacking_users = max(0, users - legitimate_users)
        if rng is None:
            rate = self.config.requests_per_user
            return legitimate_users * rate, attacking_users * rate * 2.25

        low_rate, high_rate = self._service_request_rate_range()
        average_rate = (low_rate + high_rate) / 2.0
        legitimate_requests = 0
        malicious_requests = 0
        if users <= 5000:
            for index in range(1, legitimate_users + 1):
                user_rate = rng.uniform(low_rate, high_rate) * self._variation_factor(rng)
                requests = self._sample_request_count(user_rate, rng)
                legitimate_requests += requests
                if on_client_requests:
                    on_client_requests("Legítimo", index, requests)
            for index in range(1, attacking_users + 1):
                user_rate = rng.uniform(low_rate, high_rate) * rng.uniform(1.5, 3.0)
                user_rate *= self._variation_factor(rng)
                requests = self._sample_request_count(user_rate, rng)
                malicious_requests += requests
                if on_client_requests:
                    on_client_requests("Malicioso", index, requests)
            return legitimate_requests, malicious_requests

        # Keep very large profiles responsive while preserving the same expected request rates.
        factor = self._variation_factor(rng)
        legitimate_mean = legitimate_users * average_rate * factor
        malicious_mean = attacking_users * average_rate * 2.25 * factor
        legitimate_sample = self._sample_request_count(legitimate_mean, rng)
        malicious_sample = self._sample_request_count(malicious_mean, rng)
        if on_client_requests:
            on_client_requests("Legítimo", 0, legitimate_sample)
            on_client_requests("Malicioso", 0, malicious_sample)
        return legitimate_sample, malicious_sample

    def _service_request_rate_range(self) -> tuple[float, float]:
        return {
            "Web HTTPS": (0.3, 0.7), "Web HTTP": (0.3, 0.7),
            "API HTTPS": (0.2, 0.6), "Base de datos PostgreSQL": (0.1, 0.3),
            "DNS": (0.2, 1.0), "Personalizado": (0.3, 0.7),
        }.get(self.config.service_name, (0.3, 0.7))
    @staticmethod
    def _sample_request_count(expected: float, rng: random.Random) -> int:
        """Sample a nonnegative request count for one simulated second."""
        if expected <= 0:
            return 0
        if expected < 30.0:
            threshold = math.exp(-expected)
            product = 1.0
            count = 0
            while product > threshold:
                count += 1
                product *= rng.random()
            return count - 1
        return max(0, round(rng.gauss(expected, math.sqrt(expected))))
    def _generated_requests_at(self, second: int, users: int, rng: random.Random | None = None) -> float:
        """Returns modeled request demand; this does not generate network traffic."""
        self._current_second = second
        legitimate, malicious = self._request_components(users, rng)
        return legitimate + malicious

    def _variation_factor(self, rng: random.Random | None) -> float:
        variation = self.config.random_variation_percent / 100.0
        return rng.uniform(1.0 - variation, 1.0 + variation) if rng and variation else 1.0

    def _vary(self, value: int, rng: random.Random | None) -> int:
        return min(self.config.max_users, max(0, round(value * self._variation_factor(rng))))
    @staticmethod
    def _assert_sample(sample: SimulationSample) -> None:
        assert sample.users >= 0 and sample.effective_users <= sample.users
        assert sample.users_generated == sample.users
        assert sample.requests_generated >= 0
        assert sample.generated_requests_s >= 0 and sample.processed_requests_s >= 0
        assert sample.generated_requests_s >= 0 and sample.processed_requests_s >= 0
        assert 0 <= sample.cpu_percent <= 100 and 0 <= sample.ram_percent <= 100
        assert 0 <= sample.saturation_percent <= 100
        assert sample.instances >= 1 and sample.capacity_rps >= 0
        assert all(0 <= load <= 100 for load in sample.server_loads)

    def _state(self, saturation: float, detected: bool, mitigated: bool) -> str:
        if mitigated and saturation < self.config.high_load_threshold:
            return "RECUPERADO"
        if mitigated:
            return "MITIGACIÓN ACTIVA"
        if detected:
            return "ANOMALÍA DETECTADA"
        if saturation >= self.config.saturated_threshold:
            return "SATURACIÓN"
        if saturation >= self.config.high_load_threshold:
            return "CARGA ALTA"
        return "NORMAL"


def compare_mitigations(profile: ServerProfile, config: SimulationConfig) -> list[ComparisonRow]:
    """Run the same synthetic scenario with one layer at a time and as a stack."""
    names = ["Sin mitigación", *MitigationConfigNames]
    rows: list[ComparisonRow] = []
    for name in names:
        selected = () if name == "Sin mitigación" else (name,)
        layer_config = replace(config, mitigation=replace(config.mitigation, selected=selected))
        result = SimulationEngine(profile, layer_config).run()
        rows.append(ComparisonRow(
            name=name,
            max_saturation=result.max_saturation,
            max_cpu=max((sample.cpu_percent for sample in result.samples), default=0.0),
            max_ram=max((sample.ram_percent for sample in result.samples), default=0.0),
            max_latency=max((sample.latency_ms for sample in result.samples), default=0.0),
            requests_blocked=sum(sample.requests_blocked for sample in result.samples),
            recovery_time=result.recovery_at,
        ))
    combined = replace(config, mitigation=replace(config.mitigation, selected=MitigationConfigNames))
    result = SimulationEngine(profile, combined).run()
    rows.append(ComparisonRow(
        name="Combinada",
        max_saturation=result.max_saturation,
        max_cpu=max((sample.cpu_percent for sample in result.samples), default=0.0),
        max_ram=max((sample.ram_percent for sample in result.samples), default=0.0),
        max_latency=max((sample.latency_ms for sample in result.samples), default=0.0),
        requests_blocked=sum(sample.requests_blocked for sample in result.samples),
        recovery_time=result.recovery_at,
    ))
    return rows


MitigationConfigNames = (
    "Rate Limiting", "Rate-Based Ban", "Blacklisting", "CAPTCHA / Challenge",
    "WAF / Filtrado L7", "Bot Management", "Auto Scaling", "CDN / Caching",
    "Load Balancing", "Edge / Scrubbing",
)
