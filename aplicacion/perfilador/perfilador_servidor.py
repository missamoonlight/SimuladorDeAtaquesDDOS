from __future__ import annotations

import re
from datetime import datetime

from aplicacion.modelos.perfil_servidor import NetworkInterface, ServerProfile


class ServerProfiler:
    """Parses outputs from the fixed SSH diagnostics into a ServerProfile."""

    def build_profile(self, raw: dict[str, str], source: str = "SSH") -> ServerProfile:
        system = raw.get("system", "")
        cpu = raw.get("cpu", "")
        memory = raw.get("memory", "")
        profile = ServerProfile(
            hostname=self._first(raw.get("hostname", ""), "N/D"),
            operating_system=self._os_name(system),
            kernel=self._kernel(system),
            architecture=self._architecture(system),
            uptime=self._uptime(raw.get("uptime", "")),
            cpu_model=self._lscpu(cpu, "Model name") or self._match(cpu, r"model name\s*:\s*(.+)"),
            logical_cpus=self._number(self._lscpu(cpu, "CPU(s)"), 1),
            physical_cores=self._number(self._lscpu(cpu, "Core(s) per socket"), 1),
            sockets=self._number(self._lscpu(cpu, "Socket(s)"), 1),
            cpu_frequency_mhz=self._float(self._lscpu(cpu, "CPU MHz")),
            ram_total_mb=self._memory_value(memory, "Mem:", 1),
            ram_used_mb=self._memory_value(memory, "Mem:", 2),
            ram_free_mb=self._memory_value(memory, "Mem:", 3),
            ram_available_mb=self._memory_value(memory, "Mem:", 6),
            swap_total_mb=self._memory_value(memory, "Swap:", 1),
            swap_used_mb=self._memory_value(memory, "Swap:", 2),
            disks=self._disks(raw.get("disks", "")),
            network_interfaces=self._network(raw.get("network", "")),
            primary_network_interface=self._match(raw.get("network", ""), r"^PRIMARY=(.*)$", "N/D"),
            bandwidth_source=self._bandwidth_source(self._network(raw.get("network", ""))),
            load_1m=self._load(raw.get("load", ""), 0),
            load_5m=self._load(raw.get("load", ""), 1),
            load_15m=self._load(raw.get("load", ""), 2),
            timestamp=datetime.now().isoformat(timespec="seconds"),
            source=source,
        )
        return profile

    @staticmethod
    def _first(value: str, fallback: str) -> str:
        return value.strip().splitlines()[0] if value.strip() else fallback

    @staticmethod
    def _match(value: str, pattern: str, fallback: str = "N/D") -> str:
        match = re.search(pattern, value, re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip() if match else fallback

    def _lscpu(self, output: str, key: str) -> str:
        return self._match(output, rf"^{re.escape(key)}\s*:\s*(.+)$")

    def _os_name(self, system: str) -> str:
        return self._match(system, r"^Linux\s+\S+\s+\S+\s+\S+\s+(.+)$", "Linux")

    def _kernel(self, system: str) -> str:
        parts = system.split()
        return parts[2] if len(parts) > 2 else "N/D"

    def _architecture(self, system: str) -> str:
        parts = system.split()
        return parts[-1] if parts else "N/D"

    @staticmethod
    def _uptime(output: str) -> str:
        try:
            seconds = float(output.split()[0])
            days, remainder = divmod(int(seconds), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes = remainder // 60
            return f"{days}d {hours}h {minutes}m"
        except (ValueError, IndexError):
            return output.strip() or "N/D"

    @staticmethod
    def _number(value: str, fallback: int) -> int:
        match = re.search(r"\d+", value)
        return int(match.group()) if match else fallback

    @staticmethod
    def _float(value: str) -> float:
        match = re.search(r"\d+(?:\.\d+)?", value)
        return float(match.group()) if match else 0.0

    def _memory_value(self, output: str, label: str, position: int) -> float:
        line = next((row for row in output.splitlines() if row.startswith(label)), "")
        fields = line.replace("|", " ").split()
        if len(fields) <= position:
            return 0.0
        return self._to_mb(fields[position])

    @staticmethod
    def _to_mb(value: str) -> float:
        match = re.match(r"([\d.]+)([KMGTP]?)", value.upper())
        if not match:
            return 0.0
        amount = float(match.group(1))
        multiplier = {"": 1 / (1024 * 1024), "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}.get(match.group(2), 1)
        return amount * multiplier

    @staticmethod
    def _disks(output: str) -> list[dict[str, str]]:
        disks = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 7 and parts[0].startswith("/"):
                disks.append({"unidad": parts[0], "tamaño": parts[1], "usado": parts[2], "libre": parts[3], "uso": parts[4], "montaje": " ".join(parts[6:])})
        return disks

    @staticmethod
    def _network(output: str) -> list[NetworkInterface]:
        interfaces = []
        for line in output.splitlines():
            if not line.startswith("IFACE="):
                continue
            parts = line[6:].split("|")
            if len(parts) != 5:
                continue
            name, speed, state, rx, tx = parts
            try:
                speed_value = float(speed) if float(speed) > 0 else 0.0
            except ValueError:
                speed_value = 0.0
            try:
                rx_value, tx_value = int(rx), int(tx)
            except ValueError:
                rx_value = tx_value = 0
            interfaces.append(NetworkInterface(name=name, speed_mbps=speed_value,
                                               link_state=state or "unknown",
                                               rx_bytes=rx_value, tx_bytes=tx_value))
        return interfaces or [NetworkInterface()]

    @staticmethod
    def _bandwidth_source(interfaces: list[NetworkInterface]) -> str:
        return "link_speed" if any(item.speed_mbps > 0 for item in interfaces) else "assumed_default"

    @staticmethod
    def _load(output: str, position: int) -> float:
        try:
            return float(output.split()[position])
        except (ValueError, IndexError):
            return 0.0
