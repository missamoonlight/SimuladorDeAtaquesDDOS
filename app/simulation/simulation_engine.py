from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field, replace

from app.models.server_profile import ServerProfile
from app.models.simulation_config import SimulationConfig
from app.simulation.capacity_model import CapacityModel


@dataclass
class SimulationSample:
    second: int
    users: int
    effective_users: int
    generated_requests_s: float
    processed_requests_s: float
    generated_traffic_mbps: float
    processed_traffic_mbps: float
    requests_s: float
    traffic_mbps: float
    cpu_percent: float
    ram_percent: float
    saturation_percent: float
    latency_ms: float
    state: str
    users_generated: int = 0
    users_legitimate: int = 0
    users_suspicious: int = 0
    users_blocked: int = 0
    requests_generated: float = 0.0
    requests_limited: float = 0.0
    requests_blocked: float = 0.0
    requests_challenge: float = 0.0
    requests_cache: float = 0.0
    requests_origin: float = 0.0
    traffic_after_edge_mbps: float = 0.0
    traffic_after_waf_mbps: float = 0.0
    traffic_to_origin_mbps: float = 0.0
    legitimate_preserved: float = 0.0
    false_positive_requests: float = 0.0
    instances: int = 1
    capacity_rps: float = 0.0
    sources_detected: int = 0
    sources_blocked: int = 0
    mitigation_active: str = "Ninguna"
    anomaly_score: float = 0.0
    server_loads: tuple[float, ...] = ()


@dataclass
class SimulationResult:
    samples: list[SimulationSample] = field(default_factory=list)
    detected_at: int | None = None
    mitigation_at: int | None = None
    recovery_at: int | None = None
    max_saturation: float = 0.0
    time_saturated: int = 0
    sources_detected: int = 0
    sources_blocked: int = 0

    @property
    def detection_time(self) -> int | None:
        return self.detected_at

    @property
    def mitigation_time(self) -> int | None:
        return self.mitigation_at

    @property
    def traffic_reduction_percent(self) -> float:
        generated = sum(item.generated_traffic_mbps for item in self.samples)
        processed = sum(item.traffic_to_origin_mbps for item in self.samples)
        return max(0.0, (1.0 - processed / generated) * 100.0) if generated else 0.0

    @property
    def request_reduction_percent(self) -> float:
        generated = sum(item.requests_generated for item in self.samples)
        processed = sum(item.processed_requests_s for item in self.samples)
        return max(0.0, (1.0 - processed / generated) * 100.0) if generated else 0.0

    @property
    def origin_load_reduction_percent(self) -> float:
        return self.traffic_reduction_percent

    @property
    def legitimate_traffic_preserved(self) -> float:
        return sum(item.legitimate_preserved for item in self.samples)

    @property
    def false_positive_rate(self) -> float:
        legitimate = sum(item.users_legitimate for item in self.samples)
        false_positives = sum(item.false_positive_requests for item in self.samples)
        return false_positives / max(legitimate, 1.0) * 100.0

    @property
    def mitigation_efficiency(self) -> float:
        return (self.request_reduction_percent + self.traffic_reduction_percent) / 2.0


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

    def __init__(self, profile: ServerProfile, config: SimulationConfig) -> None:
        config.validate()
        self.profile = profile
        self.config = config
        self.model = CapacityModel(profile, config)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()
        self._ban_remaining = 0
        self._blacklist_remaining = 0
        self._ban_streak = 0
        self._instances = config.mitigation.autoscaling_initial_instances

    def stop(self) -> None:
        self._stop.set()
        self._pause.set()

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def run(self, on_sample=None, on_event=None) -> SimulationResult:
        rng = random.Random(self.config.seed)
        result = SimulationResult()
        detected = False
        mitigated = False
        baseline = max(self.model.requests_per_second(self.config.initial_users), 1.0)
        anomaly_streak = 0
        for second in range(1, self.config.duration_seconds + 1):
            if self._stop.is_set():
                break
            self._pause.wait()
            generated_users = self._users_at(second)
            generated_requests = self._generated_requests_at(second, generated_users)
            legitimate_ratio = max(0.20, min(1.0, baseline / max(generated_requests, baseline)))
            legitimate_requests = generated_requests * legitimate_ratio
            malicious_requests = max(0.0, generated_requests - legitimate_requests)
            users_legitimate = int(round(generated_users * legitimate_ratio))
            users_suspicious = max(0, generated_users - users_legitimate)
            anomaly_score = min(100.0, max(0.0, (generated_requests / baseline - 1.0) * 45.0 * self.config.mitigation.anomaly_sensitivity))
            raw_cpu, raw_ram, _, raw_saturation = self.model.resource_usage(generated_users, generated_requests)
            anomaly_score = min(100.0, anomaly_score + max(0.0, raw_saturation - 70.0))
            detection_window_open = second > self.config.normal_duration_seconds + self.config.detection_delay_seconds
            if detection_window_open and anomaly_score >= self.config.mitigation.anomaly_threshold:
                anomaly_streak += 1
            else:
                anomaly_streak = 0
            if not detected and anomaly_streak >= self.config.mitigation.anomaly_window_seconds:
                detected = True
                result.detected_at = second
                if on_event:
                    on_event(f"Anomalía detectada tras {anomaly_streak} evaluaciones en t={second}s.")

            metrics = self._pipeline(
                second, generated_users, generated_requests, legitimate_requests, malicious_requests,
                users_legitimate, users_suspicious, detected, rng, on_event,
            )
            if detected and self.config.mitigation_enabled and self.config.mitigation.selected and not mitigated:
                mitigated = True
                result.mitigation_at = second
                if on_event:
                    on_event("Mitigación multicapa activada dentro del modelo.")
            if metrics["saturation"] < self.config.high_load_threshold and mitigated and result.recovery_at is None:
                result.recovery_at = second
                if on_event:
                    on_event("Servidor recuperado dentro del modelo.")
            active = ", ".join(self.config.mitigation.selected) if detected and self.config.mitigation_enabled else "Ninguna"
            sample = SimulationSample(
                second=second, users=generated_users, effective_users=int(metrics["effective_users"]),
                generated_requests_s=generated_requests, processed_requests_s=metrics["processed_requests"],
                generated_traffic_mbps=self.model.traffic_from_requests(generated_requests), processed_traffic_mbps=metrics["processed_traffic"],
                requests_s=metrics["processed_requests"], traffic_mbps=metrics["processed_traffic"],
                cpu_percent=metrics["cpu"], ram_percent=metrics["ram"], saturation_percent=metrics["saturation"],
                latency_ms=metrics["latency"], state=self._state(metrics["saturation"], detected, mitigated),
                users_generated=generated_users, users_legitimate=users_legitimate,
                users_suspicious=users_suspicious, users_blocked=metrics["users_blocked"],
                requests_generated=generated_requests, requests_limited=metrics["requests_limited"],
                requests_blocked=metrics["requests_blocked"], requests_challenge=metrics["requests_challenge"],
                requests_cache=metrics["requests_cache"], requests_origin=metrics["requests_origin"],
                traffic_after_edge_mbps=metrics["traffic_after_edge"], traffic_after_waf_mbps=metrics["traffic_after_waf"],
                traffic_to_origin_mbps=metrics["traffic_to_origin"], legitimate_preserved=metrics["legitimate_preserved"],
                false_positive_requests=metrics["false_positives"], instances=metrics["instances"],
                capacity_rps=metrics["capacity_rps"], sources_detected=metrics["sources_detected"],
                sources_blocked=metrics["sources_blocked"], mitigation_active=active, anomaly_score=anomaly_score,
                server_loads=metrics["server_loads"],
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
            time.sleep(0.04)
        return result

    def _pipeline(self, second, users, generated, legitimate, malicious, users_legitimate, users_suspicious, detected, rng, on_event):
        mitigation = self.config.mitigation
        after_edge = generated
        edge_latency = 0.0
        if mitigation.has("Edge / Scrubbing"):
            edge_latency = mitigation.edge_latency_ms
            filter_ratio = mitigation.edge_filter_percent / 100.0
            if self.model.traffic_from_requests(generated) > mitigation.edge_filter_capacity_mbps:
                filter_ratio = max(filter_ratio, 1.0 - mitigation.edge_filter_capacity_mbps / max(self.model.traffic_from_requests(generated), 0.001))
            after_edge = generated * max(0.0, 1.0 - filter_ratio)
        traffic_after_edge = self.model.traffic_from_requests(after_edge)
        cache = after_edge * mitigation.cdn_hit_ratio / 100.0 if mitigation.has("CDN / Caching") else 0.0
        origin_candidate = max(0.0, after_edge - cache)
        if mitigation.has("WAF / Filtrado L7"):
            waf_block = malicious * mitigation.waf_detection_effectiveness / 100.0
            false_positives = legitimate * mitigation.waf_false_positive_rate / 100.0
            origin_candidate = max(0.0, origin_candidate - waf_block - false_positives)
            waf_latency = mitigation.waf_latency_ms
        else:
            waf_block = false_positives = waf_latency = 0.0
        bot_block = malicious * mitigation.bot_detection_effectiveness / 100.0 * mitigation.bot_block_percent / 100.0 if mitigation.has("Bot Management") else 0.0
        challenge = (malicious * mitigation.bot_challenge_percent / 100.0 if mitigation.has("Bot Management") else 0.0)
        if mitigation.has("CAPTCHA / Challenge"):
            challenge += malicious * mitigation.captcha_challenge_percent / 100.0
        challenge_block = challenge * (1.0 - (mitigation.captcha_solve_probability / 100.0 if mitigation.has("CAPTCHA / Challenge") else 0.7))
        source_rate = generated / max(users, 1)
        detected_sources = int(users_suspicious * min(1.0, source_rate / max(mitigation.ban_threshold_rps, 1.0)))
        if mitigation.has("Rate-Based Ban") and source_rate >= mitigation.ban_threshold_rps:
            self._ban_streak += 1
            if self._ban_streak >= mitigation.ban_evaluations:
                self._ban_remaining = mitigation.ban_duration_seconds
        else:
            self._ban_streak = 0
        ban_block = malicious * mitigation.ban_source_percent / 100.0 if mitigation.has("Rate-Based Ban") and self._ban_remaining > 0 else 0.0
        self._ban_remaining = max(0, self._ban_remaining - 1)
        blacklist_block = malicious * mitigation.blacklist_detect_percent / 100.0 if mitigation.has("Blacklisting") else 0.0
        blocked_users = int(users_suspicious * mitigation.blacklist_detect_percent / 100.0) if mitigation.has("Blacklisting") else 0
        candidate = max(0.0, origin_candidate - bot_block - challenge_block - ban_block - blacklist_block)
        if mitigation.has("Rate Limiting"):
            limit = mitigation.rate_limit_rps * mitigation.rate_window_seconds
            processed_before_lb = min(candidate, limit)
        else:
            processed_before_lb = candidate
        limited = max(0.0, candidate - processed_before_lb)
        instances = self._update_autoscaling(second, processed_before_lb)
        per_instance = mitigation.autoscaling_capacity_per_instance_rps or self.model.cpu_capacity
        server_count = mitigation.load_balancer_servers if mitigation.has("Load Balancing") else 1
        capacity = self.model.capacity_for_instances(instances * server_count, per_instance)
        processed = min(processed_before_lb, capacity)
        if server_count > 1:
            if mitigation.load_balancer_algorithm == "Weighted Round Robin":
                weights = list(mitigation.load_balancer_weights[:server_count])
                weights += [1.0] * (server_count - len(weights))
                total_weight = sum(weights) or 1.0
                loads = tuple(min(100.0, processed * weight / total_weight / max(per_instance * instances, 1.0) * 100.0) for weight in weights)
            else:
                loads = tuple(min(100.0, processed / server_count / max(per_instance * instances, 1.0) * 100.0) for _ in range(server_count))
        else:
            loads = (min(100.0, processed / max(per_instance * instances, 1.0) * 100.0),)
        requests_blocked = max(0.0, generated - processed - cache)
        traffic_after_waf = self.model.traffic_from_requests(max(0.0, origin_candidate))
        traffic_origin = self.model.traffic_from_requests(processed)
        effective_users = max(0.0, users - blocked_users)
        waf_cost = mitigation.waf_cpu_cost_percent if mitigation.has("WAF / Filtrado L7") else 0.0
        cpu, ram, _, saturation = self.model.resource_usage(effective_users, processed, instances=instances * server_count, waf_cpu_cost=waf_cost)
        if mitigation.has("Auto Scaling"):
            cpu = min(100.0, cpu + instances * mitigation.autoscaling_cost_cpu_percent)
            saturation = min(100.0, max(cpu, ram))
        delay = edge_latency + waf_latency + (challenge * mitigation.captcha_delay_ms / max(generated, 1.0))
        latency = self.config.target_latency_ms * (1.0 + saturation / 100.0) + delay + rng.uniform(-3.0, 3.0)
        return {"effective_users": effective_users, "processed_requests": processed, "processed_traffic": traffic_origin, "traffic_after_edge": traffic_after_edge, "traffic_after_waf": traffic_after_waf, "traffic_to_origin": traffic_origin, "requests_limited": limited, "requests_blocked": requests_blocked, "requests_challenge": challenge, "requests_cache": cache, "requests_origin": processed, "users_blocked": blocked_users, "legitimate_preserved": max(0.0, legitimate - false_positives), "false_positives": false_positives, "instances": instances, "capacity_rps": capacity, "sources_detected": detected_sources, "sources_blocked": blocked_users, "server_loads": loads, "cpu": cpu, "ram": ram, "saturation": max(0.0, min(100.0, saturation)), "latency": max(0.0, latency)}

    def _update_autoscaling(self, second: int, incoming: float) -> int:
        mitigation = self.config.mitigation
        if not mitigation.has("Auto Scaling"):
            return 1
        per_instance = mitigation.autoscaling_capacity_per_instance_rps or self.model.cpu_capacity
        if incoming > self._instances * per_instance and second % mitigation.autoscaling_time_seconds == 0:
            self._instances = min(mitigation.autoscaling_max_instances, self._instances + 1)
        return self._instances

    def _users_at(self, second: int) -> int:
        initial, maximum = self.config.initial_users, self.config.max_users
        duration = max(self.config.duration_seconds, 1)
        if self.config.scenario == "Spike":
            return min(maximum, int(initial + (maximum - initial) * (1.0 if second <= 10 else 0.25)))
        if self.config.scenario == "Repentino":
            progress = min(1.0, second / max(1, min(self.config.sudden_ramp_seconds, duration)))
            return min(maximum, initial + int((maximum - initial) * progress))
        if self.config.scenario == "Pulsante":
            phase = (second - 1) % 20
            return min(maximum, int(initial + (maximum - initial) * (phase / 19 if phase < 10 else (19 - phase) / 10)))
        if self.config.scenario == "Personalizado":
            return min(maximum, initial + int((second - 1) * max(1, (maximum - initial) / duration)))
        return min(maximum, int(initial + (maximum - initial) * (second - 1) / max(duration - 1, 1)))

    def _generated_requests_at(self, second: int, users: int) -> float:
        """Uses the optional legacy-style intensity controls without network I/O."""
        if self.config.intensity_base_rps <= 0:
            return self.model.requests_per_second(users)
        normal_end = self.config.normal_duration_seconds
        if second <= normal_end:
            return self.config.intensity_base_rps * 0.002
        attack_elapsed = second - normal_end
        attack_duration = max(1, self.config.duration_seconds - normal_end)
        if self.config.scenario == "Spike":
            progress = 1.0 if attack_elapsed <= 10 else 0.25
        elif self.config.scenario == "Repentino":
            progress = min(1.0, attack_elapsed / max(1, self.config.sudden_ramp_seconds))
        elif self.config.scenario == "Pulsante":
            progress = 1.0 if ((attack_elapsed // 5) % 2 == 0) else 0.35
        else:
            progress = min(1.0, attack_elapsed / attack_duration)
        if self.config.scenario == "Personalizado":
            progress = users / max(self.config.max_users, 1)
        return max(0.0, self.config.intensity_base_rps * max(0.0, progress))

    @staticmethod
    def _assert_sample(sample: SimulationSample) -> None:
        assert sample.users >= 0 and sample.effective_users <= sample.users
        assert sample.users_generated == sample.users
        assert sample.requests_generated >= 0
        assert sample.generated_requests_s >= 0 and sample.processed_requests_s >= 0
        assert sample.generated_traffic_mbps >= 0 and sample.processed_traffic_mbps >= 0
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
