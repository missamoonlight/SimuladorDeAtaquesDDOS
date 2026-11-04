from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from aplicacion.interfaz.componentes_interfaz import PALETTE
from aplicacion.modelos.perfil_servidor import ServerProfile
from aplicacion.reportes.generador_reportes import save_profile


class ProfileView(ttk.Frame):
    def __init__(self, parent, on_continue, on_back):
        super().__init__(parent)
        self.profile: ServerProfile | None = None
        self.on_continue = on_continue
        self.on_back = on_back
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ttk.Label(self, text="Perfil del servidor", style="Title.TLabel", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w", pady=(12, 8))
        self.placeholder = ttk.Label(
            self,
            text="Carga un perfil para ver aquí el resumen del servidor.",
            foreground=PALETTE["muted"],
            wraplength=420,
        )
        self.placeholder.grid(row=1, column=0, sticky="w", pady=(0, 10))

        cards = ttk.Frame(self)
        cards.grid(row=2, column=0, sticky="ew")
        cards.columnconfigure(0, weight=1, uniform="profile_cards")
        cards.columnconfigure(1, weight=1, uniform="profile_cards")
        self.values: dict[str, ttk.Label] = {}
        self._build_card(cards, "Servidor", 0, 0, (
            ("hostname", "Nombre"), ("source", "Origen"), ("timestamp", "Actualizado"),
        ))
        self._build_card(cards, "Sistema", 0, 1, (
            ("operating_system", "Sistema"), ("kernel", "Kernel"), ("architecture", "Arquitectura"),
            ("uptime", "Tiempo activo"), ("load", "Carga 1 / 5 / 15 min"),
        ))
        self._build_card(cards, "Procesador", 1, 0, (
            ("cpu_model", "Modelo"), ("logical_cpus", "CPU lógicas"), ("physical_cores", "Núcleos físicos"),
            ("sockets", "Sockets"), ("cpu_frequency", "Frecuencia"),
        ))
        self._build_card(cards, "Memoria", 1, 1, (
            ("ram_total", "RAM total"), ("ram_available", "RAM disponible"), ("ram_used", "RAM usada"),
            ("ram_free", "RAM libre"), ("swap", "Swap usada / total"),
        ))

        frame = ttk.LabelFrame(self, text="Almacenamiento y red", padding=6)
        frame.grid(row=3, column=0, sticky="nsew", pady=(8, 6))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("tipo", "detalle"), show="headings")
        self.tree.heading("tipo", text="Recurso")
        self.tree.heading("detalle", text="Detalles")
        self.tree.column("tipo", width=100, minwidth=90, stretch=False, anchor="w")
        self.tree.column("detalle", width=360, minwidth=220, stretch=True, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Button-1>", self._prevent_column_change, add="+")
        vertical_scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vertical_scrollbar.set)
        horizontal_scrollbar = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=horizontal_scrollbar.set)
        actions = ttk.Frame(self)
        actions.grid(row=4, column=0, sticky="ew", pady=(4, 8))
        self.save_button = ttk.Button(actions, text="GUARDAR PERFIL", command=self.save, state="disabled")
        self.save_button.pack(side="left")
        self.continue_button = ttk.Button(actions, text="CONTINUAR A SIMULACIÓN", command=on_continue, state="disabled", style="Primary.TButton")
        self.continue_button.pack(side="left", padx=(8, 0))
        self._show_placeholder()

    def _build_card(self, parent, title, row, column, fields):
        card = ttk.LabelFrame(parent, text=title, padding=(8, 6))
        card.grid(row=row, column=column, sticky="nsew", padx=(0, 5) if column == 0 else (5, 0), pady=4)
        card.columnconfigure(1, weight=1)
        for index, (key, caption) in enumerate(fields):
            ttk.Label(card, text=caption, foreground=PALETTE["muted"]).grid(row=index, column=0, sticky="nw", padx=(0, 6), pady=2)
            value = ttk.Label(card, text="—", wraplength=150, justify="left")
            value.grid(row=index, column=1, sticky="nw", pady=2)
            self.values[key] = value

    def set_profile(self, profile: ServerProfile):
        self.profile = profile
        self.placeholder.grid_remove()
        values = {
            "hostname": profile.hostname,
            "source": profile.source,
            "timestamp": profile.timestamp,
            "operating_system": profile.operating_system,
            "kernel": profile.kernel,
            "architecture": profile.architecture,
            "uptime": profile.uptime,
            "load": f"{profile.load_1m:.2f} / {profile.load_5m:.2f} / {profile.load_15m:.2f}",
            "cpu_model": profile.cpu_model,
            "logical_cpus": f"{profile.logical_cpus:,}",
            "physical_cores": f"{profile.physical_cores:,}",
            "sockets": f"{profile.sockets:,}",
            "cpu_frequency": f"{profile.cpu_frequency_mhz:,.0f} MHz" if profile.cpu_frequency_mhz else "No disponible",
            "ram_total": self._format_memory(profile.ram_total_mb),
            "ram_available": self._format_memory(profile.ram_available_mb),
            "ram_used": self._format_memory(profile.ram_used_mb),
            "ram_free": self._format_memory(profile.ram_free_mb),
            "swap": f"{self._format_memory(profile.swap_used_mb)} / {self._format_memory(profile.swap_total_mb)}",
        }
        for key, value in values.items():
            self.values[key].configure(text=value or "No disponible")
        self.save_button.configure(state="normal")
        self.continue_button.configure(state="normal")
        for item in self.tree.get_children():
            self.tree.delete(item)
        for disk in profile.disks:
            self.tree.insert("", "end", values=("Disco", " · ".join(f"{key.capitalize()}: {value}" for key, value in disk.items())))
        for interface in profile.network_interfaces:
            self.tree.insert("", "end", values=("Red", f"{interface.name} · {interface.speed_mbps:g} Mbps · RX {interface.rx_bytes:,} B · TX {interface.tx_bytes:,} B"))

    def save(self):
        if not self.profile:
            return
        destination = filedialog.askdirectory(title="Carpeta para guardar el perfil")
        if not destination:
            return
        json_path, text_path = save_profile(self.profile, Path(destination))
        messagebox.showinfo("Perfil guardado", f"JSON: {json_path}\nTXT: {text_path}")

    def _show_placeholder(self):
        for value in self.values.values():
            value.configure(text="—")

    @staticmethod
    def _format_memory(value_mb: float) -> str:
        if value_mb <= 0:
            return "No disponible"
        return f"{value_mb:,.0f} MB ({value_mb / 1024:.2f} GB)"

    @staticmethod
    def _prevent_column_change(event):
        if event.widget.identify_region(event.x, event.y) in {"separator", "heading"}:
            return "break"
