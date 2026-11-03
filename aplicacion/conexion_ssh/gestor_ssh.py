from __future__ import annotations

import socket
from typing import Callable

import paramiko


READ_ONLY_COMMANDS: dict[str, str] = {
    "system": "uname -a",
    "hostname": "hostname",
    "uptime": "cat /proc/uptime",
    "cpu": "lscpu 2>/dev/null || cat /proc/cpuinfo",
    "memory": "free -b 2>/dev/null || cat /proc/meminfo",
    "disks": "df -hT; printf '\\n'; lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT 2>/dev/null",
    "network": "ip -br addr 2>/dev/null; printf '\\n---STATS---\\n'; ip -s link 2>/dev/null",
    "load": "cat /proc/loadavg",
}


class SSHConnectionError(RuntimeError):
    """Friendly error raised for an SSH connection or read-only collection failure."""


class SSHManager:
    """Executes only the fixed diagnostic commands listed in READ_ONLY_COMMANDS."""

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
