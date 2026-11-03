from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NetworkInterface:
    name: str = "N/D"
    speed_mbps: float = 0.0
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_packets: int = 0
    tx_packets: int = 0
    rx_errors: int = 0
    tx_errors: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0


@dataclass
class ServerProfile:
    hostname: str = "N/D"
    operating_system: str = "N/D"
    kernel: str = "N/D"
    architecture: str = "N/D"
    uptime: str = "N/D"
    cpu_model: str = "N/D"
    logical_cpus: int = 1
    physical_cores: int = 1
    sockets: int = 1
    cpu_frequency_mhz: float = 0.0
    ram_total_mb: float = 0.0
    ram_used_mb: float = 0.0
    ram_free_mb: float = 0.0
    ram_available_mb: float = 0.0
    swap_total_mb: float = 0.0
    swap_used_mb: float = 0.0
    disks: list[dict[str, str]] = field(default_factory=list)
    network_interfaces: list[NetworkInterface] = field(default_factory=list)
    load_1m: float = 0.0
    load_5m: float = 0.0
    load_15m: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    source: str = "SSH"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["network_interfaces"] = [asdict(item) for item in self.network_interfaces]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerProfile":
        values = dict(data)
        interfaces = values.get("network_interfaces", [])
        values["network_interfaces"] = [
            item if isinstance(item, NetworkInterface) else NetworkInterface(**item) for item in interfaces
        ]
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in values.items() if key in allowed})

    @property
    def ram_total_gb(self) -> float:
        return self.ram_total_mb / 1024

    @property
    def available_bandwidth_mbps(self) -> float:
        speeds = [item.speed_mbps for item in self.network_interfaces if item.speed_mbps > 0]
        return max(speeds, default=100.0)

    def readable_text(self) -> str:
        lines = [
            "=" * 40,
            "PERFIL DE CAPACIDAD",
            "=" * 40,
            "",
            f"Servidor: {self.hostname}",
            f"Origen: {self.source}",
            f"Fecha: {self.timestamp}",
            "",
            "SISTEMA",
            "-" * 40,
            f"Sistema: {self.operating_system}",
            f"Kernel: {self.kernel}",
            f"Arquitectura: {self.architecture}",
            f"Tiempo encendido: {self.uptime}",
            "",
            "CPU",
            "-" * 40,
            f"Modelo: {self.cpu_model}",
            f"CPU lógicas: {self.logical_cpus}",
            f"Núcleos físicos: {self.physical_cores}",
            f"Sockets: {self.sockets}",
            f"Frecuencia: {self.cpu_frequency_mhz or 'N/D'} MHz",
            f"Carga: {self.load_1m:.2f}, {self.load_5m:.2f}, {self.load_15m:.2f}",
            "",
            "MEMORIA",
            "-" * 40,
            f"RAM total: {self.ram_total_mb:.0f} MB",
            f"RAM usada: {self.ram_used_mb:.0f} MB",
            f"RAM disponible: {self.ram_available_mb:.0f} MB",
            f"Swap: {self.swap_used_mb:.0f}/{self.swap_total_mb:.0f} MB",
            "",
            "DISCO",
            "-" * 40,
        ]
        for disk in self.disks:
            lines.append(" | ".join(f"{key}: {value}" for key, value in disk.items()))
        lines.extend(["", "RED", "-" * 40])
        for interface in self.network_interfaces:
            lines.append(
                f"{interface.name}: {interface.speed_mbps:g} Mbps | "
                f"RX {interface.rx_bytes} B | TX {interface.tx_bytes} B | "
                f"errores RX/TX {interface.rx_errors}/{interface.tx_errors}"
            )
        lines.extend([
            "",
            "NOTA:",
            "Este perfil se utiliza únicamente para personalizar una simulación local.",
            "No se genera tráfico contra el servidor.",
        ])
        return "\n".join(lines) + "\n"


def demo_profile() -> ServerProfile:
    return ServerProfile(
        hostname="demo-servidor",
        operating_system="Ubuntu Linux (perfil demostración)",
        kernel="Linux 6.8.0-demo x86_64",
        architecture="x86_64",
        uptime="12 days, 4 hours",
        cpu_model="Intel(R) Core(TM) Ultra 7 258V",
        logical_cpus=4,
        physical_cores=4,
        sockets=1,
        cpu_frequency_mhz=3800,
        ram_total_mb=8192,
        ram_used_mb=1638,
        ram_free_mb=4710,
        ram_available_mb=6348,
        swap_total_mb=2048,
        swap_used_mb=128,
        disks=[{"unidad": "/dev/sda1", "tamaño": "80G", "usado": "24G", "libre": "56G", "uso": "30%", "montaje": "/"}],
        network_interfaces=[NetworkInterface(name="enp0s3", speed_mbps=1000)],
        load_1m=0.18,
        load_5m=0.12,
        load_15m=0.10,
        source="MODO DEMOSTRACIÓN",
    )
