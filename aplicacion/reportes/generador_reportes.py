from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from aplicacion.modelos.perfil_servidor import ServerProfile
from aplicacion.modelos.configuracion_simulacion import SimulationConfig
from aplicacion.simulacion.modelo_capacidad import CapacityModel
from aplicacion.simulacion.motor_simulacion import SimulationResult, SimulationSample


def save_profile(profile: ServerProfile, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = directory / f"perfil_{stamp}.json"
    text_path = directory / f"perfil_{stamp}.txt"
    json_path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text(profile.readable_text(), encoding="utf-8")
    return json_path, text_path


def export_csv(result: SimulationResult, directory: Path, config: SimulationConfig | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"simulacion_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "segundo", "dia_simulado", "hora_del_dia_simulada", "servicio", "puerto_servicio", "protocolo_servicio", "perfil_demanda_legitima",
            "usuarios_generados", "usuarios_legitimos", "usuarios_sospechosos", "usuarios_bloqueados",
            "solicitudes_generadas", "solicitudes_legitimas", "solicitudes_maliciosas_simuladas",
            "solicitudes_procesadas", "solicitudes_en_cola", "solicitudes_rechazadas_desbordamiento",
            "solicitudes_limitadas", "solicitudes_bloqueadas", "solicitudes_challenge", "solicitudes_cache",
            "solicitudes_al_origen", "consumo_red_rx_mbps_estimado", "consumo_red_tx_mbps_estimado",
            "cpu_percent", "ram_percent", "saturation_percent", "latency_ms",
            "instancias", "capacity_rps", "cargas_balanceador", "estado", "mitigacion_activa", "semilla",
            "variacion_aleatoria_pct",
        ])
        for sample in result.samples:
            hour_offset = (config.start_hour + (sample.second - 1) // 3600) if config else 0
            writer.writerow([
                sample.second, hour_offset // 24 + 1, f"{hour_offset % 24:02d}:00" if config else "",
                config.service_name if config else "", config.service_port if config else "",
                config.service_protocol if config else "", config.legitimate_profile if config else "", sample.users, sample.users_legitimate,
                sample.users_suspicious, sample.users_blocked, f"{sample.requests_generated:.3f}",
                f"{sample.legitimate_requests_s:.3f}", f"{sample.malicious_requests_s:.3f}",
                f"{sample.processed_requests_s:.3f}", f"{sample.requests_queued:.3f}",
                f"{sample.requests_dropped:.3f}", f"{sample.requests_limited:.3f}",
                f"{sample.requests_blocked:.3f}", f"{sample.requests_challenge:.3f}",
                f"{sample.requests_cache:.3f}", f"{sample.requests_origin:.3f}",
                f"{sample.network_rx_mbps:.6f}", f"{sample.network_tx_mbps:.6f}",
                f"{sample.cpu_percent:.3f}", f"{sample.ram_percent:.3f}",
                f"{sample.saturation_percent:.3f}", f"{sample.latency_ms:.3f}", sample.instances,
                f"{sample.capacity_rps:.3f}", ";".join(f"{load:.1f}%" for load in sample.server_loads),
                sample.state, sample.mitigation_active, config.seed if config else "",
                config.random_variation_percent if config else "",
            ])
    if result.client_hourly:
        detail_path = path.with_name(f"{path.stem}_clientes_por_hora.csv")
        with detail_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "hora_relativa", "dia_simulado", "hora_del_dia_simulada", "segundo_inicio", "segundo_fin",
                "cliente_simulado", "ip_origen_sintetica", "puerto_origen_simulado", "tipo_trafico",
                "servicio", "puerto_destino", "protocolo", "granularidad", "solicitudes",
                "solicitudes_estimadas_al_servidor", "respuestas_estimadas", "bytes_entrada_estimados",
                "bytes_salida_estimados", "promedio_rx_mbps_estimado", "promedio_tx_mbps_estimado",
                "fuente_detectada_por_modelo", "fuente_bloqueada_por_blacklisting",
            ])
            for item in result.client_hourly:
                writer.writerow([
                    item.hour_index, item.simulation_day, f"{item.hour_of_day:02d}:00",
                    item.period_start_second, item.period_end_second, item.client_id, item.source_ip,
                    item.source_port, item.traffic_class, item.service_name, item.service_port,
                    item.service_protocol, item.granularity, item.requests,
                    f"{item.estimated_inbound_requests:.3f}", f"{item.estimated_responses:.3f}",
                    item.inbound_bytes, item.outbound_bytes, f"{item.inbound_average_mbps:.6f}",
                    f"{item.outbound_average_mbps:.6f}", item.source_detected, item.source_blocked,
                ])
    return path


def export_pdf(profile: ServerProfile, config: SimulationConfig, result: SimulationResult,
               model: CapacityModel, directory: Path, output_path: Path | None = None) -> Path:
    """Export a compact, printable summary and the four modeled time series."""
    if output_path is None:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"reporte_resiliencia_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        path = output_path
    with PdfPages(path) as pdf:
        summary = Figure(figsize=(8.27, 11.69), facecolor="white")
        axis = summary.add_subplot(111)
        axis.axis("off")
        lines = [
            "REPORTE DEL SIMULADOR DE RESILIENCIA", "",
            f"Servidor de referencia: {profile.hostname} ({profile.source})",
            f"Perfil consultado: {profile.timestamp}",
            f"CPU: {profile.cpu_model} · {profile.logical_cpus} procesadores lógicos",
            f"RAM total: {profile.ram_total_mb:.0f} MB · disponible al perfilar: {profile.ram_available_mb:.0f} MB",
            f"Servicio modelado: {config.service_name} · {config.service_port}/{config.service_protocol}",
            f"Demanda legítima: {config.legitimate_profile} · ataque: {config.scenario}",
            f"Duración: {config.duration_seconds} s · usuarios iniciales: {config.initial_users}",
            f"Capas: {', '.join(config.mitigation.selected) or 'ninguna'} · semilla: {config.seed}", "",
            "RESULTADOS DEL MODELO", "",
            f"Saturación máxima estimada: {result.max_saturation:.1f}%",
            f"CPU máxima estimada: {max((s.cpu_percent for s in result.samples), default=0):.1f}%",
            f"RAM máxima estimada: {max((s.ram_percent for s in result.samples), default=0):.1f}%",
            f"Detección: {result.detected_at if result.detected_at is not None else 'no detectada'} s",
            f"Mitigación: {result.mitigation_at if result.mitigation_at is not None else 'no activada'} s",
            f"Recuperación: {result.recovery_at if result.recovery_at is not None else 'no alcanzada'} s",
            f"Falsos positivos del modelo: {result.false_positive_rate:.2f}%", "",
            result.capacity_conclusion, "",
            "Interpretación: la CPU, RAM, solicitudes y saturación de esta sección son estimaciones matemáticas;",
            "no son mediciones de carga durante la simulación y no prueban la capacidad real del servidor.",
            "El perfil SSH es una captura de referencia. Las direcciones de clientes son sintéticas.", "",
            model.summary(),
        ]
        axis.text(0.06, 0.97, "\n".join(lines), va="top", ha="left", fontsize=10, color="#17251e", linespacing=1.5, wrap=True)
        pdf.savefig(summary, bbox_inches="tight")

        chart = Figure(figsize=(11.69, 8.27), facecolor="white")
        axes = [chart.add_subplot(2, 2, i) for i in range(1, 5)]
        x = [sample.second for sample in result.samples]
        series = (
            ("Demanda y respuesta (solicitudes/s)", (("Legítimas", [s.legitimate_requests_s for s in result.samples]), ("Maliciosas simuladas", [s.malicious_requests_s for s in result.samples]), ("Atendidas", [s.processed_requests_s + s.requests_cache for s in result.samples]))),
            ("Recursos estimados (%)", (("CPU", [s.cpu_percent for s in result.samples]), ("RAM", [s.ram_percent for s in result.samples]))),
            ("Consumo de red estimado (Mbps)", (("RX", [s.network_rx_mbps for s in result.samples]), ("TX", [s.network_tx_mbps for s in result.samples]))),
            ("Saturación estimada (%)", (("Saturación", [s.saturation_percent for s in result.samples]),)),
        )
        for axis, (title, lines) in zip(axes, series):
            axis.set_title(title)
            for label, values in lines:
                axis.plot(x, values, label=label, linewidth=1.5)
            axis.set_xlabel("Tiempo simulado (s)")
            axis.grid(alpha=0.25)
            axis.legend(frameon=False)
        chart.suptitle("Series estimadas por el modelo local", fontsize=14)
        chart.tight_layout(rect=(0, 0, 1, 0.96))
        pdf.savefig(chart, bbox_inches="tight")
    return path


BATCH_CSV_COLUMNS = (
    "id_simulacion", "duracion_s", "semilla", "variacion_aleatoria_pct",
    "escenario_ataque", "perfil_trafico_legitimo", "servicio",
    "cpu_nucleos", "ram_total_mb", "usuarios_iniciales", "usuarios_legitimos_pico",
    "usuarios_maliciosos_pico", "capas_mitigacion", "solicitudes_legitimas_totales",
    "solicitudes_maliciosas_totales", "solicitudes_procesadas_totales",
    "solicitudes_en_cola_max", "solicitudes_rechazadas_totales", "cpu_estimada_max_pct",
    "ram_estimada_max_pct", "saturacion_max_pct", "latencia_promedio_ms",
    "latencia_max_ms", "red_rx_promedio_mbps", "red_rx_max_mbps",
    "red_tx_promedio_mbps", "red_tx_max_mbps", "ataque_detectado",
    "tiempo_deteccion_s", "tiempo_inicio_mitigacion_s", "tiempo_recuperacion_s",
    "nivel_impacto",
)


def summarize_batch_run(batch_number: int, config: SimulationConfig,
                        profile: ServerProfile, result: SimulationResult,
                        session_id: str = "") -> dict[str, object]:
    """Create one row from actual samples produced by one local engine run."""
    samples: list[SimulationSample] = result.samples
    maximum_saturation = max((sample.saturation_percent for sample in samples), default=0.0)
    if maximum_saturation < config.high_load_threshold:
        impact = "Estable"
    elif maximum_saturation < min(75.0, config.saturated_threshold):
        impact = "Carga alta"
    elif maximum_saturation < config.saturated_threshold:
        impact = "Cerca del límite"
    else:
        impact = "Crítico"

    return {
        "id_simulacion": f"SIM-{session_id}-{batch_number:04d}" if session_id else f"SIM-{batch_number:04d}",
        "duracion_s": len(samples),
        "semilla": config.seed,
        "variacion_aleatoria_pct": config.random_variation_percent,
        "escenario_ataque": config.scenario,
        "perfil_trafico_legitimo": config.legitimate_profile,
        "servicio": config.service_name,
        "cpu_nucleos": profile.logical_cpus,
        "ram_total_mb": profile.ram_total_mb,
        "usuarios_iniciales": config.initial_users,
        "usuarios_legitimos_pico": max((sample.users_legitimate for sample in samples), default=0),
        "usuarios_maliciosos_pico": max((sample.users_suspicious for sample in samples), default=0),
        "capas_mitigacion": "; ".join(config.mitigation.selected) or "Ninguna",
        "solicitudes_legitimas_totales": sum(sample.legitimate_requests_s for sample in samples),
        "solicitudes_maliciosas_totales": sum(sample.malicious_requests_s for sample in samples),
        "solicitudes_procesadas_totales": sum(sample.processed_requests_s + sample.requests_cache for sample in samples),
        "solicitudes_en_cola_max": max((sample.requests_queued for sample in samples), default=0.0),
        "solicitudes_rechazadas_totales": sum(
            sample.requests_dropped + sample.requests_limited + sample.requests_blocked
            for sample in samples
        ),
        "cpu_estimada_max_pct": max((sample.cpu_percent for sample in samples), default=0.0),
        "ram_estimada_max_pct": max((sample.ram_percent for sample in samples), default=0.0),
        "saturacion_max_pct": maximum_saturation,
        "latencia_promedio_ms": sum(sample.latency_ms for sample in samples) / len(samples) if samples else 0.0,
        "latencia_max_ms": max((sample.latency_ms for sample in samples), default=0.0),
        "red_rx_promedio_mbps": sum(sample.network_rx_mbps for sample in samples) / len(samples) if samples else 0.0,
        "red_rx_max_mbps": max((sample.network_rx_mbps for sample in samples), default=0.0),
        "red_tx_promedio_mbps": sum(sample.network_tx_mbps for sample in samples) / len(samples) if samples else 0.0,
        "red_tx_max_mbps": max((sample.network_tx_mbps for sample in samples), default=0.0),
        "ataque_detectado": result.detected_at is not None,
        "tiempo_deteccion_s": result.detected_at if result.detected_at is not None else "",
        "tiempo_inicio_mitigacion_s": result.mitigation_at if result.mitigation_at is not None else "",
        "tiempo_recuperacion_s": result.recovery_at if result.recovery_at is not None else "",
        "nivel_impacto": impact,
    }


def export_batch_csv(rows: list[dict[str, object]], path: Path) -> Path:
    """Export one actual simulator summary row per completed batch run."""
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=BATCH_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            rounded_row = {
                key: f"{value:.2f}" if isinstance(value, float) else value
                for key, value in row.items()
            }
            writer.writerow(rounded_row)
    return path


def generate_report(profile: ServerProfile, config: SimulationConfig, result: SimulationResult, model: CapacityModel, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"reporte_resiliencia_{datetime.now():%Y%m%d_%H%M%S}.txt"
    maximum = max(result.samples, key=lambda item: item.saturation_percent, default=None)
    max_cpu = max((item.cpu_percent for item in result.samples), default=0.0)
    max_ram = max((item.ram_percent for item in result.samples), default=0.0)
    max_rx = max((item.network_rx_mbps for item in result.samples), default=0.0)
    max_tx = max((item.network_tx_mbps for item in result.samples), default=0.0)
    hourly_lines = []
    for start in range(0, len(result.samples), 3600):
        interval = result.samples[start:start + 3600]
        if not interval:
            continue
        elapsed = len(interval)
        hour_offset = config.start_hour + start // 3600
        rx_average = sum(item.network_rx_mbps for item in interval) / elapsed
        tx_average = sum(item.network_tx_mbps for item in interval) / elapsed
        hourly_lines.append(
            f"D{hour_offset // 24 + 1} {hour_offset % 24:02d}:00 ({interval[0].second}-{interval[-1].second}s, {elapsed}s): "
            f"solicitudes generadas {sum(item.requests_generated for item in interval):.0f}; "
            f"procesadas {sum(item.processed_requests_s for item in interval):.0f}; "
            f"RX estimado promedio {rx_average:.4f} Mbps ({rx_average * elapsed / 8:.3f} MB); "
            f"TX estimado promedio {tx_average:.4f} Mbps ({tx_average * elapsed / 8:.3f} MB); "
            f"usuarios legitimos promedio {sum(item.users_legitimate for item in interval) / elapsed:.1f}; "
            f"maliciosos promedio {sum(item.users_suspicious for item in interval) / elapsed:.1f}"
        )
    lines = [
        "=" * 40, "REPORTE DE SIMULACION", "=" * 40, "",
        f"Fecha: {datetime.now():%Y-%m-%d %H:%M:%S}", "",
        "PERFIL DEL SERVIDOR", "-" * 40,
        f"Servidor: {profile.hostname}", f"Origen: {profile.source}", f"CPU: {profile.cpu_model}",
        f"CPU logicas: {profile.logical_cpus}", f"RAM total: {profile.ram_total_mb:.0f} MB",
        f"RAM disponible al perfilar: {profile.ram_available_mb:.0f} MB | libre: {profile.ram_free_mb:.0f} MB",
        f"Swap al perfilar: {profile.swap_used_mb:.0f}/{profile.swap_total_mb:.0f} MB",
        f"Captura del perfil: {profile.timestamp}", "",
        "CONFIGURACION", "-" * 40,
        f"Usuarios iniciales: {config.initial_users}",
        f"Carga maxima estimada por el perfil: {config.max_users}",
        f"Duracion: {config.duration_seconds}s",
        f"Variacion aleatoria: {config.random_variation_percent:g}% | semilla: {config.seed}",
        f"Actividad media por usuario: {config.requests_per_user:.2f} solicitudes/s",
        f"Perfil de demanda legitima: {config.legitimate_profile}",
        f"Escenario de ataque modelado: {config.scenario}", f"Umbral de deteccion: {config.detection_threshold}%",
        f"Mitigaciones: {', '.join(config.mitigation.selected) or 'Ninguna'}", "",
        "RESULTADOS", "-" * 40,
        f"Maximo de usuarios: {max((item.users for item in result.samples), default=0)}",
        f"Maxima CPU: {max_cpu:.2f}%", f"Maxima RAM: {max_ram:.2f}%",
        f"Consumo maximo estimado RX: {max_rx:.4f} Mbps", f"Consumo maximo estimado TX: {max_tx:.4f} Mbps",
        f"Maxima saturacion: {maximum.saturation_percent:.2f}%" if maximum else "Maxima saturacion: 0%",
        f"Tiempo saturado: {result.time_saturated}s",
        f"Tiempo de deteccion: {result.detected_at if result.detected_at is not None else 'N/D'}s",
        f"Tiempo de mitigacion: {result.mitigation_at if result.mitigation_at is not None else 'N/D'}s",
        f"Tiempo de recuperacion: {result.recovery_at if result.recovery_at is not None else 'N/D'}s",
        f"Reduccion de solicitudes al servidor: {result.request_reduction_percent:.2f}%",
        f"Solicitudes legitimas preservadas: {result.legitimate_traffic_preserved:.2f}",
        f"Tasa de falsos positivos: {result.false_positive_rate:.2f}%", "",
        "MITIGACION", "-" * 40,
        f"Limite de solicitudes aproximado por origen: {config.mitigation.rate_limit_rps:g} solicitudes/s",
        f"Cache hit ratio: {config.mitigation.cdn_hit_ratio:g}%",
        f"Edge filtering: {config.mitigation.edge_filter_percent:g}%",
        f"Instancias maximas: {config.mitigation.autoscaling_max_instances}", "",
        model.summary(), "", "CONCLUSION", "-" * 40,
        result.capacity_conclusion,
        "La evaluación se limita al escenario, hardware modelado y capas seleccionadas.",
        "CPU, RAM, solicitudes y saturacion son estimaciones matematicas; no se midieron durante esta simulacion.",
        "El perfil SSH corresponde a una captura de referencia. La telemetria en vivo es una consulta separada.",
        "El consumo RX/TX se estima con tamanos promedio asociados al servicio; no limita la capacidad ni modifica la saturacion.",
        "La capacidad es una estimacion educativa; no representa una prueba de carga real.",
        "La simulacion se ejecuto localmente. No se genero trafico contra un servidor.",
        "Las direcciones y los puertos mostrados son sinteticos; no representan conexiones observadas.", "",
        "RESUMEN POR HORA SIMULADA", "-" * 40,
    ]
    lines.extend(hourly_lines or ["No hay muestras para resumir."])
    lines.extend(["", "SERVICIO Y PUERTOS", "-" * 40,
                  f"Servicio modelado: {config.service_name} | puerto {config.service_port}/{config.service_protocol}",
                  f"Hora simulada de inicio: D1 {config.start_hour:02d}:00",
                  "", "CLIENTES Y FUENTES SINTETICAS POR HORA", "-" * 40])
    lines.append("Hora | IP:puerto origen -> servicio:puerto | tipo | solicitudes | solicitudes al servidor | respuestas est. | RX/TX Mbps | detectada | bloqueada")
    for item in sorted(result.client_hourly, key=lambda row: row.inbound_average_mbps + row.outbound_average_mbps, reverse=True)[:50]:
        lines.append(
            f"D{item.simulation_day} {item.hour_of_day:02d}:00 ({item.period_start_second}-{item.period_end_second}s) | "
            f"{item.client_id} {item.source_ip}:{item.source_port} -> {item.service_name}:{item.service_port} | "
            f"{item.traffic_class} | {item.requests} | {item.estimated_inbound_requests:.1f} | {item.estimated_responses:.1f} | "
            f"{item.inbound_average_mbps:.4f}/{item.outbound_average_mbps:.4f} | "
            f"{item.source_detected} | {item.source_blocked}"
        )
    lines.append("Se muestran las 50 fuentes con mas solicitudes; el CSV de detalle incluye todas.")
    lines.append("La atribucion de deteccion y bloqueo es aproximada y usa contadores agregados del modelo.")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
