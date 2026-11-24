from __future__ import annotations

import socket
import time
from typing import Callable

import paramiko


READ_ONLY_COMMANDS: dict[str, str] = {
    "system": "uname -a",
    "hostname": "hostname",
    "uptime": "cat /proc/uptime",
    "cpu": "lscpu 2>/dev/null || cat /proc/cpuinfo",
    "memory": "free -b 2>/dev/null || cat /proc/meminfo",
    "disks": "df -hT; printf '\\n'; lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT 2>/dev/null",
    "network": "printf 'PRIMARY=%s\\n' \"$(ip route show default 2>/dev/null | awk 'NR==1 {print $5}')\"; for path in /sys/class/net/*; do iface=${path##*/}; [ \"$iface\" = lo ] && continue; speed=$(cat \"$path/speed\" 2>/dev/null); state=$(cat \"$path/operstate\" 2>/dev/null); rx=$(cat \"$path/statistics/rx_bytes\" 2>/dev/null); tx=$(cat \"$path/statistics/tx_bytes\" 2>/dev/null); printf 'IFACE=%s|%s|%s|%s|%s\\n' \"$iface\" \"$speed\" \"$state\" \"$rx\" \"$tx\"; done",
    "load": "cat /proc/loadavg",
}

# Fixed, read-only snapshot used only when the user explicitly opens live monitoring.
LIVE_TELEMETRY_COMMAND = r'''printf 'CPU='; awk '/^cpu / {for(i=2;i<=NF;i++) printf "%s%s", $i, (i<NF?",":""); print ""; exit}' /proc/stat
awk '/^(MemTotal|MemAvailable|MemFree|SwapTotal|SwapFree):/ {printf "%s=%s\n", $1, $2}' /proc/meminfo
printf 'NET='; awk -F'[: ]+' 'NR>2 && $2!="lo" {rx+=$3; tx+=$11} END {printf "%0.f,%0.f\n",rx,tx}' /proc/net/dev
printf 'PROC\n'; ps -eo pid=,ppid=,pcpu=,pmem=,rss=,nlwp=,comm= --sort=-pcpu 2>/dev/null | head -n 8
printf 'PORTS\n'; ss -lntup 2>/dev/null | head -n 16'''


class SSHConnectionError(RuntimeError):
    """Friendly error raised for an SSH connection or read-only collection failure."""


class SSHManager:
    """Executes only fixed, read-only system diagnostics; never accepts shell input."""

    def __init__(self, host: str, port: int, username: str, password: str = "", key_filename: str = "") -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.client = paramiko.SSHClient()
        # Paramiko's default RejectPolicy rejects hosts absent from known_hosts.
        # Load the user's system known_hosts so host identity is checked.
        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(paramiko.RejectPolicy())

    def connect(self) -> None:
        options: dict[str, object] = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": 12,
            "banner_timeout": 12,
            "auth_timeout": 12,
            "look_for_keys": not bool(self.key_filename or self.password),
            "allow_agent": not bool(self.key_filename or self.password),
        }
        if self.password:
            options["password"] = self.password
        if self.key_filename:
            options["key_filename"] = self.key_filename
        try:
            self.client.connect(**options)
        except paramiko.AuthenticationException as error:
            raise SSHConnectionError("Autenticación rechazada: revisa usuario, contraseña o clave SSH.") from error
        except (paramiko.SSHException, socket.timeout, OSError) as error:
            raise SSHConnectionError(f"No se pudo conectar al servidor: {error}") from error

    def collect(self, progress: Callable[[str], None] | None = None) -> dict[str, str]:
        results: dict[str, str] = {}
        try:
            self.connect()
            for name, command in READ_ONLY_COMMANDS.items():
                if progress:
                    progress(f"Obteniendo {name}...")
                _, stdout, stderr = self.client.exec_command(command, timeout=15)
                output = stdout.read().decode("utf-8", errors="replace").strip()
                if not output:
                    output = stderr.read().decode("utf-8", errors="replace").strip()
                results[name] = output or "N/D"
            return results
        except paramiko.AuthenticationException as error:
            raise SSHConnectionError("Autenticación rechazada.") from error
        except (paramiko.SSHException, socket.timeout, OSError) as error:
            raise SSHConnectionError(f"La consulta SSH falló: {error}") from error
        finally:
            self.client.close()

    def read_live_snapshot(self, previous: dict | None = None) -> dict:
        """Read resource counters and top processes over the existing SSH session."""
        try:
            _, stdout, stderr = self.client.exec_command(LIVE_TELEMETRY_COMMAND, timeout=10)
            output = stdout.read().decode("utf-8", errors="replace")
            if not output.strip():
                raise SSHConnectionError(stderr.read().decode("utf-8", errors="replace").strip() or "Sin datos de telemetría.")
        except (paramiko.SSHException, socket.timeout, OSError) as error:
            raise SSHConnectionError(f"Falló la lectura de telemetría: {error}") from error

        values: dict[str, str] = {}
        process_lines: list[str] = []
        port_lines: list[str] = []
        in_processes = False
        in_ports = False
        for line in output.splitlines():
            if line == "PROC":
                in_processes = True
                in_ports = False
                continue
            if line == "PORTS":
                in_processes = False
                in_ports = True
                continue
            if in_ports:
                if line.strip() and not line.lstrip().startswith("Netid"):
                    port_lines.append(line.strip())
                continue
            if in_processes:
                if line.strip():
                    process_lines.append(line.strip())
            elif "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip()

        now = time.monotonic()
        elapsed = max(0.1, now - previous["_time"]) if previous else 0.0
        cpu = [int(value) for value in values.get("CPU", "").split(",") if value]
        network = [int(value) for value in values.get("NET", "0,0").split(",")[:2]]
        metrics = {key: float(value) / 1024 for key, value in values.items()
                   if key in {"MemTotal:", "MemAvailable:", "MemFree:", "SwapTotal:", "SwapFree:"}}
        if len(cpu) >= 4:
            total = sum(cpu)
            idle = cpu[3] + (cpu[4] if len(cpu) > 4 else 0)
            if previous and previous.get("_cpu"):
                total_delta = max(1, total - sum(previous["_cpu"]))
                idle_delta = max(0, idle - (previous["_cpu"][3] + (previous["_cpu"][4] if len(previous["_cpu"]) > 4 else 0)))
                cpu_percent = max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100))
            else:
                cpu_percent = 0.0
        else:
            cpu_percent = 0.0
        if previous and elapsed > 0 and len(network) >= 2 and len(previous.get("_network", [])) >= 2:
            rx_mbps = max(0, network[0] - previous["_network"][0]) * 8 / elapsed / 1_000_000
            tx_mbps = max(0, network[1] - previous["_network"][1]) * 8 / elapsed / 1_000_000
        else:
            rx_mbps = tx_mbps = 0.0
        total_mem = metrics.get("MemTotal:", 0.0)
        available = metrics.get("MemAvailable:", 0.0)
        swap_total = metrics.get("SwapTotal:", 0.0)
        swap_free = metrics.get("SwapFree:", 0.0)
        processes = []
        for line in process_lines:
            fields = line.split()
            if len(fields) >= 7:
                try:
                    processes.append({"pid": int(fields[0]), "ppid": int(fields[1]), "cpu": float(fields[2]),
                                      "memoria_pct": float(fields[3]), "rss_mb": int(fields[4]) / 1024,
                                      "hilos": int(fields[5]), "nombre": " ".join(fields[6:])})
                except ValueError:
                    continue
        return {
            "cpu_percent": cpu_percent, "ram_total_mb": total_mem,
            "ram_available_mb": available, "ram_free_mb": metrics.get("MemFree:", 0.0),
            "ram_used_mb": max(0.0, total_mem - available),
            "swap_total_mb": swap_total, "swap_used_mb": max(0.0, swap_total - swap_free),
            "swap_percent": (swap_total - swap_free) / swap_total * 100 if swap_total else 0.0,
            "network_rx_mbps": rx_mbps, "network_tx_mbps": tx_mbps,
            "processes": processes, "listening_ports": port_lines, "timestamp": time.strftime("%H:%M:%S"),
            "_cpu": cpu, "_network": network, "_time": now,
        }

    def close(self) -> None:
        self.client.close()
