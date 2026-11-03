"""Run the protocol's full local factorial experiment from a saved profile."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.models.server_profile import NetworkInterface, ServerProfile, demo_profile
from app.simulation.experiment_design import CONFIRMATION_SECONDS, SCENARIOS, STRATEGIES, USER_LEVELS
from app.simulation.protocol_model import ProtocolSimulation
from app.simulation.protocol_parameters import ProtocolParameters
from app.simulation.simulated_server import SimulatedServer


SUMMARY_FIELDS = (
    "scenario_id", "profile_id", "repetition", "seed", "peak_users", "scenario",
    "strategy", "confirmation_seconds", "capacity_rps", "cpu_capacity_rps",
    "ram_capacity_rps", "network_capacity_rps", "connections_capacity_rps",
    "bottleneck", "max_saturation_percent", "max_cpu_percent", "max_ram_percent",
    "max_network_percent", "max_connections_percent", "served_proportion",
    "most_severe_state", "detection_time_s", "recovery_time_s", "recovery_censored",
)
TRACE_FIELDS = (
    "scenario_id", "repetition", "seed", "second", "phase", "condition",
    "virtual_users", "effective_demand_rps", "cpu_percent", "ram_percent",
    "network_percent", "connections_percent", "saturation_percent", "served_rps",
    "state", "detection_time_s", "recovery_time_s", "strategy", "bottleneck",
)


def experimental_profiles(profile: ServerProfile) -> dict[str, ServerProfile]:
    """Build a larger P2 profile and separate its bottleneck from P1's."""
    p2 = replace(
        profile,
        hostname=f"{profile.hostname}-P2-derivado",
        logical_cpus=max(1, profile.logical_cpus) * 4,
        physical_cores=max(1, profile.physical_cores) * 4,
        ram_total_mb=profile.ram_total_mb * 2,
        ram_available_mb=max(profile.ram_available_mb, profile.ram_total_mb * 0.65) * 2,
        source=f"Derivado de {profile.source}: CPU x4, RAM x2, red constante",
    )
    def capacities(item: ServerProfile) -> dict[str, float]:
        return SimulatedServer.capacities_for(item, ProtocolParameters())

    p1_capacity = capacities(profile)
    p2_capacity = capacities(p2)
    p1_bottleneck = min(p1_capacity, key=p1_capacity.get)
    if min(p2_capacity, key=p2_capacity.get) == p1_bottleneck:
        other_capacity = min(value for key, value in p2_capacity.items() if key != p1_bottleneck)
        target = other_capacity * 1.05
        if p1_bottleneck == "CPU":
            threads = max(p2.logical_cpus, int(target * 0.005) + 1)
            p2 = replace(p2, logical_cpus=threads, physical_cores=max(p2.physical_cores, threads))
        elif p1_bottleneck == "RAM":
            ram = max(p2.ram_available_mb, target * 0.05 * 0.5)
            p2 = replace(p2, ram_available_mb=ram, ram_total_mb=max(p2.ram_total_mb, ram))
        elif p1_bottleneck == "Red":
            speed = target * 160_000 / 1_000_000
            interfaces = [replace(item, speed_mbps=speed) for item in p2.network_interfaces]
            if not interfaces:
                interfaces = [NetworkInterface(name="model-link", speed_mbps=speed)]
            p2 = replace(p2, network_interfaces=interfaces)
        p2 = replace(p2, source=f"Derivado de {profile.source}; escalado para cuello de botella distinto de P1")
    return {"P1": profile, "P2": p2}


def _seed(profile_id: str, users: int, scenario: str, repetition: int) -> int:
    # Same seed across strategy and detection-time levels, as specified.
    value = f"{profile_id}|{users}|{scenario}|{repetition}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(value).digest()[:4], "big")


def run_factorial(profile: ServerProfile, output_dir: Path, repetitions: int = 30,
                  progress: Callable[[int, int], None] | None = None) -> tuple[Path, Path]:
    if repetitions < 1:
        raise ValueError("Las repeticiones deben ser al menos 1.")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    summary_path = output_dir / f"experimento_resumen_{stamp}.csv"
    trace_path = output_dir / f"experimento_bitacora_{stamp}.csv.gz"
    profiles = experimental_profiles(profile)
    conditions = []
    for profile_id, server in profiles.items():
        for users in USER_LEVELS:
            for scenario in SCENARIOS:
                for strategy in STRATEGIES:
                    for confirm in CONFIRMATION_SECONDS:
                        conditions.append((profile_id, server, users, scenario, strategy, confirm, False))
        # One no-attack control for each profile; repetitions still receive seeds.
        conditions.append((profile_id, server, 0, "Control", "Ninguna", 5, True))
    expected = len(conditions) * repetitions
    done = 0
    with summary_path.open("w", newline="", encoding="utf-8-sig") as summary_handle, \
         gzip.open(trace_path, "wt", newline="", encoding="utf-8-sig") as trace_handle:
        summary_writer = csv.DictWriter(summary_handle, fieldnames=SUMMARY_FIELDS)
        trace_writer = csv.DictWriter(trace_handle, fieldnames=TRACE_FIELDS)
        summary_writer.writeheader()
        trace_writer.writeheader()
        for profile_id, server, users, scenario, strategy, confirm, control in conditions:
            for repetition in range(1, repetitions + 1):
                seed = _seed(profile_id, users, scenario, repetition)
                run_scenario = "Gradual" if control else scenario
                result = ProtocolSimulation(server, users, run_scenario, strategy, confirm, seed, control=control).run()
                scenario_id = f"{profile_id}-{users:05d}-{scenario.upper()}-{strategy.upper().replace(' ', '_')}-D{confirm:02d}"
                if control:
                    scenario_id = f"{profile_id}-CONTROL"
                caps = result.capacities
                summary_writer.writerow({
                    "scenario_id": scenario_id, "profile_id": profile_id, "repetition": repetition,
                    "seed": seed, "peak_users": users, "scenario": scenario,
                    "strategy": strategy, "confirmation_seconds": confirm,
                    "capacity_rps": f"{result.capacity_rps:.6f}",
                    "cpu_capacity_rps": f"{caps['CPU']:.6f}", "ram_capacity_rps": f"{caps['RAM']:.6f}",
                    "network_capacity_rps": f"{caps['Red']:.6f}", "connections_capacity_rps": f"{caps['Conexiones']:.6f}",
                    "bottleneck": result.bottleneck, "max_saturation_percent": f"{result.max_saturation_percent:.6f}",
                    "max_cpu_percent": f"{result.max_cpu_percent:.6f}", "max_ram_percent": f"{result.max_ram_percent:.6f}",
                    "max_network_percent": f"{result.max_network_percent:.6f}",
                    "max_connections_percent": f"{result.max_connections_percent:.6f}",
                    "served_proportion": f"{result.served_proportion:.6f}",
                    "most_severe_state": result.most_severe_state,
                    "detection_time_s": result.detection_time_s if result.detection_time_s is not None else "",
                    "recovery_time_s": result.recovery_time_s if result.recovery_time_s is not None else "",
                    "recovery_censored": result.recovery_censored,
                })
                for sample in result.samples:
                    trace_writer.writerow({
                        "scenario_id": scenario_id, "repetition": repetition, "seed": seed,
                        "second": sample.second, "phase": sample.phase,
                        "condition": "CONTROL" if control else "ATTACK",
                        "virtual_users": f"{sample.virtual_users:.6f}",
                        "effective_demand_rps": f"{sample.effective_demand_rps:.6f}",
                        "cpu_percent": f"{sample.cpu_percent:.6f}", "ram_percent": f"{sample.ram_percent:.6f}",
                        "network_percent": f"{sample.network_percent:.6f}",
                        "connections_percent": f"{sample.connections_percent:.6f}",
                        "saturation_percent": f"{sample.saturation_percent:.6f}",
                        "served_rps": f"{sample.served_rps:.6f}", "state": sample.state,
                        "detection_time_s": sample.detection_time_s if sample.detection_time_s is not None else "",
                        "recovery_time_s": sample.recovery_time_s if sample.recovery_time_s is not None else "",
                        "strategy": sample.strategy, "bottleneck": sample.bottleneck,
                    })
                done += 1
                if progress and (done % 10 == 0 or done == expected):
                    progress(done, expected)
    metadata = {
        "summary": summary_path.name, "trace": trace_path.name,
        "profiles": {key: value.to_dict() for key, value in profiles.items()},
        "derived_profile": "P2: CPU threads x4, RAM x2 inicialmente; se ajusta el recurso limitante si P2 conserva el cuello de botella de P1",
        "bandwidth_mbps_used": {key: value.available_bandwidth_mbps for key, value in profiles.items()},
        "bandwidth_source": {
            key: "ServerProfile" if any(item.speed_mbps > 0 for item in value.network_interfaces)
            else "default model value 100 Mbps; declare and calibrate during pilot"
            for key, value in profiles.items()
        },
        "repetitions": repetitions, "runs": expected,
        "factors": {"users": USER_LEVELS, "scenarios": SCENARIOS, "strategies": STRATEGIES,
                    "detection_confirmation_seconds": CONFIRMATION_SECONDS},
        "model": {"time_step_seconds": 1, "phases_seconds": {"normal": 60, "attack": 120, "recovery": 120},
                  "capacity_formulas": {"cpu": "threads / 0.005", "ram": "available_MB / (0.05 * 0.5)",
                                        "network": "Mbps * 1e6 / 160000", "connections": "256 * threads / 0.05"},
                  "noise": "normal multiplicative SD=5%, clipped to +/-15%",
                  "normal_users": "20% of estimated capacity", "requests_per_user_second": 0.2,
                  "inertia_seconds": 10,
                  "mitigation_factors": {"Limitación de tasa": 0.5, "Filtrado": 0.3,
                                          "CAPTCHA": 0.4, "Escalamiento": 2.0},
                  "recovery_rule": "saturation <70% for 10 consecutive seconds; censored at 120 seconds"},
    }
    (output_dir / f"experimento_configuracion_{stamp}.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path, trace_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta el experimento factorial local del protocolo.")
    parser.add_argument("--profile", type=Path, help="Perfil JSON exportado. Si se omite, usa el perfil demo.")
    parser.add_argument("--output", type=Path, default=Path("data/reports"))
    parser.add_argument("--repetitions", type=int, default=30, help="30 para experimento; menor valor para piloto.")
    args = parser.parse_args()
    profile = ServerProfile.from_dict(json.loads(args.profile.read_text(encoding="utf-8"))) if args.profile else demo_profile()
    summary, trace = run_factorial(profile, args.output, args.repetitions,
                                   lambda done, total: print(f"Ejecuciones: {done}/{total}"))
    print(f"Resumen: {summary}\nBitácora: {trace}")


if __name__ == "__main__":
    main()
