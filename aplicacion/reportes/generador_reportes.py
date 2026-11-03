from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from aplicacion.modelos.perfil_servidor import ServerProfile
from aplicacion.modelos.configuracion_simulacion import SimulationConfig
from aplicacion.simulacion.modelo_capacidad import CapacityModel
from aplicacion.simulacion.motor_simulacion import SimulationResult


def save_profile(profile: ServerProfile, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = directory / f"perfil_{stamp}.json"
    text_path = directory / f"perfil_{stamp}.txt"
    json_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text(profile.readable_text(), encoding="utf-8")
    return json_path, text_path


def export_csv(result: SimulationResult, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"simulacion_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["segundo", "usuarios_generados", "usuarios_legitimos", "usuarios_sospechosos", "usuarios_bloqueados", "requests_generadas", "requests_procesadas", "requests_limitadas", "requests_bloqueadas", "requests_challenge", "requests_cache", "requests_origen", "traffic_generated_mbps", "traffic_after_edge_mbps", "traffic_after_waf_mbps", "traffic_to_origin_mbps", "cpu_percent", "ram_percent", "saturation_percent", "latency_ms", "instancias", "capacity_rps", "cargas_balanceador", "estado", "mitigacion_activa"])
        for sample in result.samples:
            writer.writerow([sample.second, sample.users, sample.users_legitimate, sample.users_suspicious, sample.users_blocked, f"{sample.requests_generated:.3f}", f"{sample.processed_requests_s:.3f}", f"{sample.requests_limited:.3f}", f"{sample.requests_blocked:.3f}", f"{sample.requests_challenge:.3f}", f"{sample.requests_cache:.3f}", f"{sample.requests_origin:.3f}", f"{sample.generated_traffic_mbps:.3f}", f"{sample.traffic_after_edge_mbps:.3f}", f"{sample.traffic_after_waf_mbps:.3f}", f"{sample.traffic_to_origin_mbps:.3f}", f"{sample.cpu_percent:.3f}", f"{sample.ram_percent:.3f}", f"{sample.saturation_percent:.3f}", f"{sample.latency_ms:.3f}", sample.instances, f"{sample.capacity_rps:.3f}", ";".join(f"{load:.1f}%" for load in sample.server_loads), sample.state, sample.mitigation_active])
    return path


def generate_report(profile: ServerProfile, config: SimulationConfig, result: SimulationResult, model: CapacityModel, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"reporte_resiliencia_{datetime.now():%Y%m%d_%H%M%S}.txt"
    maximum = max(result.samples, key=lambda item: item.saturation_percent, default=None)
    max_traffic = max((item.traffic_mbps for item in result.samples), default=0.0)
    max_cpu = max((item.cpu_percent for item in result.samples), default=0.0)
    max_ram = max((item.ram_percent for item in result.samples), default=0.0)
    lines = [
        "=" * 40, "REPORTE DE SIMULACIÓN", "=" * 40, "",
        f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}", "",
        "PERFIL DEL SERVIDOR", "-" * 40,
        f"Servidor: {profile.hostname}", f"Origen: {profile.source}", f"CPU: {profile.cpu_model}",
        f"CPU lógicas: {profile.logical_cpus}", f"RAM: {profile.ram_total_mb:.0f} MB", f"Red: {profile.available_bandwidth_mbps:g} Mbps", "",
        "CONFIGURACIÓN", "-" * 40,
        f"Usuarios iniciales: {config.initial_users}", f"Usuarios máximos: {config.max_users}", f"Duración: {config.duration_seconds}s",
        f"Intensidad base: {config.intensity_base_rps:g} req/s", f"Inicio de ataque: {config.normal_duration_seconds}s", f"Tiempo detección: {config.detection_delay_seconds}s",
        f"Ancho de banda configurado: {config.bandwidth_mbps:g} Mbps (0 = perfil SSH)",
        f"Requests por usuario: {config.requests_per_user}", f"Bytes por request: {config.request_bytes}", f"Bytes por response: {config.response_bytes}",
        f"Escenario: {config.scenario}", f"Umbral de detección: {config.detection_threshold}%", f"Mitigaciones: {', '.join(config.mitigation.selected) or 'Ninguna'}", "",
        "RESULTADOS", "-" * 40,
        f"Máxima cantidad de usuarios: {max((item.users for item in result.samples), default=0)}",
        f"Máximo tráfico procesado: {max_traffic:.2f} Mbps", f"Máxima CPU: {max_cpu:.2f}%", f"Máxima RAM: {max_ram:.2f}%",
        f"Máxima saturación: {maximum.saturation_percent:.2f}%" if maximum else "Máxima saturación: 0%",
        f"Tiempo saturado: {result.time_saturated}s", f"Tiempo de detección: {result.detected_at if result.detected_at is not None else 'N/D'}s",
        f"Tiempo de mitigación: {result.mitigation_at if result.mitigation_at is not None else 'N/D'}s",
        f"Tiempo de recuperación: {result.recovery_at if result.recovery_at is not None else 'N/D'}s",
        f"Fuentes detectadas: {result.sources_detected}", f"Fuentes bloqueadas: {result.sources_blocked}", "",
        "EFECTIVIDAD", "-" * 40,
        f"Traffic Reduction: {result.traffic_reduction_percent:.2f}%",
        f"Request Reduction: {result.request_reduction_percent:.2f}%",
        f"Origin Load Reduction: {result.origin_load_reduction_percent:.2f}%",
        f"CPU Reduction: estimada por comparación de escenarios",
        f"RAM Reduction: estimada por comparación de escenarios",
        f"Legitimate Traffic Preserved: {result.legitimate_traffic_preserved:.2f} requests",
        f"False Positive Rate: {result.false_positive_rate:.2f}%",
        f"Mitigation Efficiency: {result.mitigation_efficiency:.2f}%", "",
        "MITIGACIÓN", "-" * 40,
        f"Límite de requests: {config.mitigation.rate_limit_rps:g} req/s", f"Cache hit ratio: {config.mitigation.cdn_hit_ratio:g}%",
        f"Edge filtering: {config.mitigation.edge_filter_percent:g}%", f"Instancias máximas: {config.mitigation.autoscaling_max_instances}", "",
        model.summary(), "", "CONCLUSIÓN", "-" * 40,
        "La simulación relaciona usuarios, solicitudes, tamaño de datos y recursos estimados del perfil.",
        "Capacidad estimada por el modelo; esta estimación es educativa y matemática y no representa una prueba de carga real.",
        "SIMULATED_COLLAPSE significa únicamente que el modelo superó la capacidad estimada; no significa que el servidor real haya caído.",
        "La simulación se ejecutó localmente. No se generó tráfico contra el servidor.", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
