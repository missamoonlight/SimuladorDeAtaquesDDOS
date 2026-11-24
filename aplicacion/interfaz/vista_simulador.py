from __future__ import annotations

import threading
import sys
import subprocess
import random
import tkinter as tk
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from aplicacion.interfaz.componentes_interfaz import PALETTE
from aplicacion.conexion_ssh.gestor_ssh import SSHConnectionError, SSHManager
from aplicacion.modelos.perfil_servidor import ServerProfile
from aplicacion.modelos.configuracion_simulacion import MITIGATION_NAMES, MitigationConfig, SimulationConfig, preset
from aplicacion.reportes.generador_reportes import (
    export_batch_csv, export_csv, export_pdf, generate_report,
    summarize_batch_run,
)
from aplicacion.simulacion.modelo_capacidad import CapacityModel
from aplicacion.simulacion.motor_simulacion import (
    SATURATION_NEAR_LIMIT, SimulationEngine, SimulationResult, SimulationSample,
)


class SimulatorView(ttk.Frame):
    def __init__(self, parent, on_back):
        super().__init__(parent)
        self.profile: ServerProfile | None = None
        self.engine: SimulationEngine | None = None
        self.result: SimulationResult | None = None
        self.batch_summaries: list[dict[str, object]] = []
        self.batch_graph_data: tuple[SimulationConfig, SimulationResult] | None = None
        self.batch_mode = False
        self.batch_stop_event = threading.Event()
        self.running = False
        self.paused = False
        self.reset_pending = False
        self.return_pending = False
        self.active_config: SimulationConfig | None = None
        self.active_duration_unit = "Segundos"
        self.samples: list[SimulationSample] = []
        self.console_table_active = False
        self.monitor_credentials: dict[str, str] | None = None
        self._telemetry_stop = None
        self._telemetry_window = None
        self.vars = {name: tk.StringVar(value=value) for name, value in {
            "initial": "20", "duration": "60", "latency": "200", "detect": "70", "rate_limit": "1", "cache_hit": "80", "edge_filter": "90", "anomaly_window": "3",
        }.items()}
        self.variation_level = tk.StringVar(value="Media")
        self.batch_count = tk.StringVar(value="1000")
        self.service_name = tk.StringVar(value="Web HTTPS")
        self.service_port = tk.StringVar(value="443")
        self.service_protocol = tk.StringVar(value="TCP")
        self.start_hour = tk.StringVar(value="0")
        self.vars["seed"] = tk.StringVar(value="")
        self.duration_unit = tk.StringVar(value="Segundos")
        self.scenario = tk.StringVar(value="Gradual")
        self.preset_name = tk.StringVar(value="Protección básica")
        self.layer_vars = {name: tk.BooleanVar(value=name == "Rate Limiting") for name in MITIGATION_NAMES}
        self.mitigation_fields = {}
        self.mitigation_help = {}
        self.status = tk.StringVar(value="Sin simulación activa")
        self._build(on_back)

    def _build(self, on_back):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        controls = ttk.Frame(self)
        controls.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=(0, 10))
        self.controls_panel = controls
        controls.columnconfigure(0, weight=1, uniform="parameter_groups")
        controls.columnconfigure(1, weight=1, uniform="parameter_groups")
        controls.rowconfigure(0, weight=1)
        controls.rowconfigure(1, weight=1)

        def add_field(parent, row, label, key):
            field_label = ttk.Label(parent, text=label)
            field_label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=5)
            if key == "duration":
                duration_controls = ttk.Frame(parent)
                duration_controls.grid(row=row, column=1, sticky="ew", pady=5)
                ttk.Entry(duration_controls, textvariable=self.vars[key], width=7).pack(side="left", fill="x", expand=True)
                self.duration_combo = ttk.Combobox(duration_controls, textvariable=self.duration_unit, values=("Segundos", "Minutos"), state="readonly", width=10)
                self.duration_combo.pack(side="left", padx=(5, 0))
            else:
                entry = ttk.Entry(parent, textvariable=self.vars[key], width=12)
                entry.grid(row=row, column=1, sticky="ew", pady=5)
                if key in ("rate_limit", "edge_filter", "cache_hit"):
                    self.mitigation_fields[key] = (field_label, entry)
            parent.columnconfigure(1, weight=1)

        general = ttk.LabelFrame(controls, text="USUARIOS Y DURACIÓN", padding=10)
        general.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        general_fields = (("Usuarios iniciales", "initial"), ("Duración", "duration"))
        for row, (label, key) in enumerate(general_fields):
            add_field(general, row, label, key)
        ttk.Label(general, text="Patron del ataque").grid(row=len(general_fields), column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Combobox(general, textvariable=self.scenario, values=("Gradual", "Repentino", "Pulsante", "Spike", "Personalizado"), state="readonly", width=14).grid(row=len(general_fields), column=1, sticky="ew", pady=5)
        ttk.Label(general, text="Demanda legítima").grid(row=len(general_fields) + 1, column=0, sticky="w", padx=(0, 8), pady=5)
        self.legitimate_profile = tk.StringVar(value="Variación normal")
        ttk.Combobox(general, textvariable=self.legitimate_profile, values=("Variación normal", "Hora pico", "Evento / inscripciones"), state="readonly", width=22).grid(row=len(general_fields) + 1, column=1, sticky="ew", pady=5)
        ttk.Label(general, text="El perfil agrega horas pico o eventos legítimos para comparar con el tráfico malicioso.", style="Subtitle.TLabel", wraplength=300).grid(row=len(general_fields) + 2, column=0, columnspan=2, sticky="w", pady=(4, 2))
        self.capacity_hint = tk.StringVar(value="Carga máxima estimada: carga un perfil")
        ttk.Label(general, textvariable=self.capacity_hint, style="Subtitle.TLabel", wraplength=300).grid(row=len(general_fields) + 3, column=0, columnspan=2, sticky="w", pady=(4, 2))

        traffic = ttk.LabelFrame(controls, text="SOLICITUDES Y VARIACION", padding=10)
        traffic.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Label(traffic, text="Variacion entre corridas").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Combobox(traffic, textvariable=self.variation_level, values=("Ninguna", "Baja", "Media", "Alta"), state="readonly", width=14).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(traffic, text="El modelo genera solicitudes al azar segun la cantidad de usuarios.", style="Subtitle.TLabel", wraplength=300).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.advanced_button = ttk.Button(traffic, text="Opciones avanzadas +", command=self._toggle_advanced)
        self.advanced_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        self.advanced_frame = ttk.LabelFrame(traffic, text="OPCIONES AVANZADAS", padding=6)
        self.advanced_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Label(self.advanced_frame, text="Latencia objetivo (ms)").grid(row=0, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(self.advanced_frame, textvariable=self.vars["latency"], width=14).grid(row=0, column=1, sticky="ew", padx=5, pady=4)
        ttk.Label(self.advanced_frame, text="Servicio simulado").grid(row=1, column=0, sticky="w", padx=5, pady=4)
        self.service_combo = ttk.Combobox(
            self.advanced_frame, textvariable=self.service_name,
            values=("Web HTTPS", "Web HTTP", "API HTTPS", "Base de datos PostgreSQL", "DNS", "Personalizado"),
            state="readonly", width=22,
        )
        self.service_combo.grid(row=1, column=1, sticky="ew", padx=5, pady=4)
        self.service_combo.bind("<<ComboboxSelected>>", self._service_changed)
        ttk.Label(self.advanced_frame, text="Puerto modelado").grid(row=2, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(self.advanced_frame, textvariable=self.service_port, width=14).grid(row=2, column=1, sticky="ew", padx=5, pady=4)
        ttk.Label(self.advanced_frame, text="Protocolo").grid(row=3, column=0, sticky="w", padx=5, pady=4)
        ttk.Combobox(self.advanced_frame, textvariable=self.service_protocol, values=("TCP", "UDP"), state="readonly", width=14).grid(row=3, column=1, sticky="ew", padx=5, pady=4)
        ttk.Label(self.advanced_frame, text="Hora inicial simulada (0-23)").grid(row=4, column=0, sticky="w", padx=5, pady=4)
        ttk.Spinbox(self.advanced_frame, textvariable=self.start_hour, from_=0, to=23, width=14).grid(row=4, column=1, sticky="ew", padx=5, pady=4)
        ttk.Label(self.advanced_frame, text="Semilla (vacia = aleatoria)").grid(row=5, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(self.advanced_frame, textvariable=self.vars["seed"], width=14).grid(row=5, column=1, sticky="ew", padx=5, pady=4)
        ttk.Label(self.advanced_frame, text="El servicio cambia costos educativos asumidos por solicitud y sesión; puerto y protocolo describen el escenario, no inspeccionan el servidor.", style="Subtitle.TLabel", wraplength=360, justify="left").grid(row=6, column=0, columnspan=2, sticky="w", padx=5, pady=(4, 2))
        ttk.Label(self.advanced_frame, text="Simulaciones por lote (1–1000)").grid(row=7, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(self.advanced_frame, textvariable=self.batch_count, width=14).grid(row=7, column=1, sticky="ew", padx=5, pady=4)
        self.batch_button = ttk.Button(self.advanced_frame, text="EJECUTAR LOTE", command=self.start_batch)
        self.batch_button.grid(row=8, column=0, columnspan=2, sticky="ew", padx=5, pady=(6, 4))
        ttk.Label(
            self.advanced_frame,
            text="Cada simulación del lote usa una semilla propia; el CSV tendrá una fila por simulación.",
            style="Subtitle.TLabel", wraplength=360, justify="left",
        ).grid(row=9, column=0, columnspan=2, sticky="w", padx=5, pady=(2, 4))
        self.advanced_frame.columnconfigure(1, weight=1)
        self.advanced_frame.grid_remove()

        defense = ttk.LabelFrame(controls, text="MITIGACIÓN", padding=10)
        defense.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=6, pady=6)
        defense.columnconfigure(0, weight=0)
        defense.columnconfigure(1, weight=0)
        defense.columnconfigure(2, weight=1)
        ttk.Label(defense, text="Capas activas", foreground=PALETTE["green"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        layers = ttk.Frame(defense)
        layers.grid(row=1, column=0, columnspan=2, sticky="ew")
        for index, name in enumerate(MITIGATION_NAMES):
            layers.columnconfigure(index // 5, weight=1, uniform="mitigation_columns")
            tk.Checkbutton(layers, text=name, variable=self.layer_vars[name], command=self._update_mitigation_controls, bg=PALETTE["panel"], fg=PALETTE["text"], activebackground=PALETTE["panel"], activeforeground=PALETTE["green"], selectcolor="#1d4d38", anchor="w").grid(row=index % 5, column=index // 5, sticky="w", padx=(0, 8), pady=1)
        ttk.Label(
            defense,
            text="La mayoría de las defensas puede actuar desde el inicio. El blacklist espera a que se detecte el ataque.",
            style="Subtitle.TLabel", wraplength=190, justify="left",
        ).grid(row=1, column=2, sticky="w", padx=(10, 0))
        ttk.Label(defense, text="Preset").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 4))
        preset_combo = ttk.Combobox(defense, textvariable=self.preset_name, values=("Protección básica", "Protección web", "Protección avanzada", "Alta disponibilidad", "Defensa multicapa"), state="readonly", width=18)
        preset_combo.grid(row=2, column=1, sticky="ew", pady=(8, 4))
        preset_combo.bind("<<ComboboxSelected>>", self._apply_preset)
        ttk.Label(
            defense,
            text="Activa de una vez un conjunto de defensas. Puedes cambiar las casillas después.",
            style="Subtitle.TLabel", wraplength=190, justify="left",
        ).grid(row=2, column=2, sticky="w", padx=(10, 0), pady=(8, 4))
        defense_fields = (("Umbral de anomalía (%)", "detect"), ("Límite req/s por origen", "rate_limit"), ("Cache hit %", "cache_hit"), ("Edge filtrado %", "edge_filter"), ("Ventana de anomalía (s)", "anomaly_window"))
        help_text = {
            "detect": "Qué tan inusual debe ser el tráfico para que el sistema sospeche de un ataque.",
            "rate_limit": "Máximo aproximado por segundo para cada origen; el exceso se limita antes de entrar a la cola del servidor.",
            "cache_hit": "Solo se aplica a contenido que puede guardarse; API y contenido dinámico suelen volver al servidor.",
            "edge_filter": "Porcentaje estimado del tráfico malicioso que el filtro perimetral detiene antes del servidor.",
            "anomaly_window": "Segundos seguidos que debe durar el comportamiento inusual para detectarlo.",
        }
        for row, (label, key) in enumerate(defense_fields, start=3):
            add_field(defense, row, label, key)
            help_label = ttk.Label(
                defense, text=help_text[key], style="Subtitle.TLabel",
                wraplength=190, justify="left",
            )
            help_label.grid(row=row, column=2, sticky="w", padx=(10, 0), pady=2)
            self.mitigation_help[key] = help_label
        defense.columnconfigure(1, weight=1)
        self._update_mitigation_controls()

        actions = ttk.Frame(defense)
        actions.grid(row=8, column=0, columnspan=2, pady=(12, 2))
        self.start_button = ttk.Button(actions, text="INICIAR EXPLORACIÓN", command=self.start, style="Primary.TButton", width=23)
        self.start_button.pack(side="left", padx=5)
        ttk.Button(defense, text="VOLVER AL PERFIL", command=on_back, width=20).grid(row=9, column=0, columnspan=2, sticky="e", pady=(3, 2))
        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky="nsew")
        self.right_panel = right
        right.grid_remove()
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        status_frame = ttk.Frame(right)
        status_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status, style="Title.TLabel", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(status_frame, mode="determinate", maximum=100, value=0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.graph_actions = ttk.Frame(right)
        self.graph_actions.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.pause_button = ttk.Button(self.graph_actions, text="PAUSAR", command=self.pause, state="disabled")
        self.pause_button.pack(side="left", padx=(0, 6))
        self.stop_button = ttk.Button(self.graph_actions, text="DETENER", command=self.stop, state="disabled", style="Danger.TButton")
        self.stop_button.pack(side="left", padx=6)
        self.reset_button = ttk.Button(self.graph_actions, text="REINICIAR", command=self.reset)
        self.reset_button.pack(side="left", padx=6)
        self.export_single_pdf_button = ttk.Button(
            self.graph_actions, text="GUARDAR GRÁFICAS PDF", command=self.save_pdf,
        )
        self.telemetry_button = ttk.Button(self.graph_actions, text="TELEMETRÍA SSH", command=self.open_live_telemetry, state="disabled")
        self.telemetry_button.pack(side="left", padx=6)
        self.trace_button = ttk.Button(self.graph_actions, text="RUTA AL SERVIDOR", command=self.trace_route, state="disabled")
        self.trace_button.pack(side="left", padx=6)
        self.export_batch_csv_button = ttk.Button(self.graph_actions, text="CSV DEL LOTE", command=self.save_batch_csv, state="disabled")
        self.export_batch_pdf_button = ttk.Button(self.graph_actions, text="PDF SIMULACIÓN 1", command=self.save_batch_pdf, state="disabled")
        ttk.Button(self.graph_actions, text="VOLVER A CONFIGURACIÓN", command=self.return_to_explorer).pack(side="right", padx=6)
        self.figure = Figure(figsize=(10, 7), dpi=100, facecolor=PALETTE["panel"])
        self.axes = [self.figure.add_subplot(2, 2, index) for index in range(1, 5)]
        self.figure.tight_layout(pad=2.5)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.chart_widget = self.canvas.get_tk_widget()
        self.chart_widget.grid(row=1, column=0, sticky="nsew")
        self.chart_widget.grid_remove()
        self.chart_interactions = self._install_chart_interactions(self.figure, self.axes, self.canvas)
        self.live_report = tk.Text(right, height=9, state="disabled", bg="#0f1916", fg=PALETTE["text"], relief="flat", font=("Consolas", 10), wrap="word")
        self.live_report.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.event_log = tk.Text(right, height=5, state="disabled", bg="#0f1916", fg="#89a79a", relief="flat", font=("Consolas", 10), wrap="word")
        self.event_log.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self._set_live_report("EXPLORACIÓN INTERACTIVA\n\nLos resultados se mostrarán aquí durante la simulación.")
        self._draw_empty()

    def set_profile(self, profile: ServerProfile):
        self.profile = profile
        self._update_capacity_hint()
        estimate = CapacityModel(profile, self._config()).summary() if self._valid_config(show_error=False) else "Perfil listo. Configura la simulación."
        self._log(estimate)

    def set_monitor_credentials(self, credentials: dict[str, str] | None) -> None:
        self.monitor_credentials = dict(credentials) if credentials else None
        if hasattr(self, "telemetry_button"):
            self.telemetry_button.configure(state="normal" if credentials else "disabled")
            self.trace_button.configure(state="normal" if credentials else "disabled")

    def _estimated_max_users(self) -> int:
        if not self.profile:
            return 1
        capacity_config = SimulationConfig(
            initial_users=0, max_users=1,
            requests_per_user=self._average_service_rate(), service_name=self.service_name.get(), seed=0,
        )
        return max(1, CapacityModel(self.profile, capacity_config).estimate().estimated_users)
    def _update_capacity_hint(self, *_args):
        if not hasattr(self, "capacity_hint"):
            return
        if not self.profile:
            self.capacity_hint.set("Carga máxima estimada: carga un perfil")
            return
        estimate = self._estimated_max_users()
        try:
            initial = int(float(self.vars["initial"].get() or 0))
        except ValueError:
            initial = 0
        note = " Reduce los usuarios iniciales para continuar." if initial > estimate else ""
        self.capacity_hint.set(f"Orientación del modelo para este servicio: hasta {estimate:,} usuarios estimados con estos supuestos; no es un límite medido.{note}")

    def _config(self) -> SimulationConfig:
        number = lambda key: float(self.vars[key].get())
        selected = tuple(name for name, variable in self.layer_vars.items() if variable.get())
        duration_seconds = int(number("duration")) * (60 if self.duration_unit.get() == "Minutos" else 1)
        mitigation = MitigationConfig(
            selected=selected, rate_limit_rps=number("rate_limit"),
            cdn_hit_ratio=number("cache_hit"), edge_filter_percent=number("edge_filter"),
            anomaly_threshold=number("detect"), anomaly_window_seconds=int(number("anomaly_window")),
        )
        seed_text = self.vars["seed"].get().strip()
        seed = int(seed_text) if seed_text else None
        variation = {"Ninguna": 0.0, "Baja": 5.0, "Media": 10.0, "Alta": 20.0}[self.variation_level.get()]
        return SimulationConfig(
            initial_users=int(number("initial")), max_users=self._estimated_max_users(),
            duration_seconds=duration_seconds, requests_per_user=self._average_service_rate(),
            service_name=self.service_name.get(), service_port=int(self.service_port.get()),
            service_protocol=self.service_protocol.get(), start_hour=int(self.start_hour.get()),
            legitimate_profile=self.legitimate_profile.get(),
            target_latency_ms=number("latency"), scenario=self.scenario.get(),
            detection_threshold=number("detect"), random_variation_percent=variation,
            seed=seed, real_time=True, mitigation=mitigation,
        )
    def _average_service_rate(self) -> float:
        rates = {
            "Web HTTPS": (0.3, 0.7), "Web HTTP": (0.3, 0.7),
            "API HTTPS": (0.2, 0.6), "Base de datos PostgreSQL": (0.1, 0.3),
            "DNS": (0.2, 1.0), "Personalizado": (0.3, 0.7),
        }
        low, high = rates.get(self.service_name.get(), (0.3, 0.7))
        return (low + high) / 2.0

    def _service_changed(self, _event=None):
        default_ports = {
            "Web HTTPS": 443, "Web HTTP": 80, "API HTTPS": 443,
            "Base de datos PostgreSQL": 5432, "DNS": 53,
        }
        port = default_ports.get(self.service_name.get())
        if port is not None:
            self.service_port.set(str(port))
        self.service_protocol.set("UDP" if self.service_name.get() == "DNS" else "TCP")
        self._update_capacity_hint()
    def _update_mitigation_controls(self):
        if not hasattr(self, "mitigation_fields") or not self.mitigation_fields:
            return
        layer_for_field = {
            "rate_limit": "Rate Limiting",
            "edge_filter": "Edge / Scrubbing",
            "cache_hit": "CDN / Caching",
        }
        for key, layer_name in layer_for_field.items():
            label, entry = self.mitigation_fields[key]
            if self.layer_vars[layer_name].get():
                label.grid()
                entry.grid()
                self.mitigation_help[key].grid()
            else:
                label.grid_remove()
                entry.grid_remove()
                self.mitigation_help[key].grid_remove()
    def _toggle_advanced(self):
        if self.advanced_frame.winfo_manager():
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="Opciones avanzadas +")
        else:
            self.advanced_frame.grid()
            self.advanced_button.configure(text="Opciones avanzadas −")

    def _apply_preset(self, _event=None):
        selected = preset(self.preset_name.get()).selected
        for name, variable in self.layer_vars.items():
            variable.set(name in selected)
        self._update_mitigation_controls()

    def _valid_config(self, show_error=True) -> bool:
        try:
            config = self._config()
            config.validate()
            return True
        except (ValueError, TypeError) as error:
            if show_error:
                messagebox.showerror("Configuración inválida", str(error))
            return False

    def start(self):
        if self.running or not self.profile or not self._valid_config():
            return
        self.batch_mode = False
        self.batch_summaries = []
        self.batch_graph_data = None
        self.export_single_pdf_button.pack_forget()
        self.export_batch_csv_button.pack_forget()
        self.export_batch_pdf_button.pack_forget()
        self.samples = []
        self.result = None
        self.running = True
        self.paused = False
        self.start_button.configure(state="disabled")
        self.batch_button.configure(state="disabled")
        self.pause_button.configure(state="normal", text="⏸ PAUSAR")
        config = self._config()
        self.active_config = config
        self.active_duration_unit = self.duration_unit.get()
        self._start_console_table(config)
        self.controls_panel.grid_remove()
        self.right_panel.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.graph_actions.grid()
        self.live_report.grid_remove()
        self.event_log.grid_remove()
        self.chart_widget.grid()
        self.stop_button.configure(state="normal")
        self.status.set(f"Exploración en ejecución · {config.scenario} · {self._duration_display(0, config.duration_seconds)}")
        self.progress_bar.configure(maximum=config.duration_seconds, value=0)
        self.engine = SimulationEngine(self.profile, config)
        threading.Thread(target=self._run_worker, daemon=True).start()
        self._log("Simulación iniciada. No se genera tráfico de red.")

    def start_batch(self):
        if self.running or not self.profile or not self._valid_config():
            return
        try:
            count = int(self.batch_count.get())
            if not 1 <= count <= 1000:
                raise ValueError("La cantidad de simulaciones por lote debe estar entre 1 y 1000.")
        except (TypeError, ValueError) as error:
            messagebox.showerror("Cantidad inválida", str(error) or "Escribe un número entero de simulaciones entre 1 y 1000.")
            return

        config = self._config()
        self.active_config = config
        self.active_duration_unit = self.duration_unit.get()
        self.batch_mode = True
        self.batch_summaries = []
        self.batch_graph_data = None
        self.export_single_pdf_button.pack_forget()
        self.batch_stop_event.clear()
        self.samples = []
        self.result = None
        self.running = True
        self.paused = False
        self.start_button.configure(state="disabled")
        self.batch_button.configure(state="disabled")
        self.pause_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.export_batch_csv_button.configure(state="disabled")
        self.export_batch_pdf_button.configure(state="disabled")
        self.export_batch_csv_button.pack(side="left", padx=6)
        self.export_batch_pdf_button.pack(side="left", padx=6)
        self.controls_panel.grid_remove()
        self.right_panel.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.graph_actions.grid()
        self.live_report.grid()
        self.event_log.grid()
        self.chart_widget.grid_remove()
        self._set_live_report(
            f"SIMULACIÓN POR LOTES\n\nSe ejecutará un lote con {count} simulaciones independientes. "
            "Cada simulación usa datos generados por el motor, una semilla distinta "
            "y una variación pequeña en los usuarios iniciales. No se envía tráfico al servidor."
        )
        self.status.set(f"Preparando un lote de {count} simulaciones · {config.duration_seconds} s por simulación")
        self.progress_bar.configure(maximum=count, value=0)
        self._log(f"Iniciando un lote con {count} simulaciones independientes del motor local.")
        session_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        threading.Thread(target=self._run_batch_worker, args=(config, count, session_id), daemon=True).start()

    def _run_batch_worker(self, base_config: SimulationConfig, count: int, session_id: str) -> None:
        assert self.profile is not None
        profile = self.profile
        seed_source = base_config.seed if base_config.seed is not None else random.SystemRandom().randrange(0, 2**32)
        rng = random.Random(seed_source)
        used_seeds: set[int] = set()
        rows: list[dict[str, object]] = []
        graph_data: tuple[SimulationConfig, SimulationResult] | None = None
        error_message = ""

        for batch_number in range(1, count + 1):
            if self.batch_stop_event.is_set():
                break
            run_seed = rng.randrange(0, 2**32)
            while run_seed in used_seeds:
                run_seed = rng.randrange(0, 2**32)
            used_seeds.add(run_seed)

            user_delta = max(1, round(base_config.initial_users * 0.05)) if base_config.initial_users else 0
            varied_users = base_config.initial_users + rng.randint(-user_delta, user_delta) if user_delta else 0
            varied_users = max(0, min(base_config.max_users, varied_users))
            run_config = replace(
                base_config,
                initial_users=varied_users,
                seed=run_seed,
                real_time=False,
                random_variation_percent=max(base_config.random_variation_percent, 5.0),
            )
            try:
                self.engine = SimulationEngine(profile, run_config, fast_forward=True)
                result = self.engine.run()
                if len(result.samples) == run_config.duration_seconds:
                    rows.append(summarize_batch_run(batch_number, run_config, profile, result, session_id))
                    if graph_data is None:
                        graph_data = (run_config, result)
                self.after(0, self._batch_progress, batch_number, count, len(rows))
            except Exception as error:
                error_message = str(error)
                break

        self.after(0, self._finished_batch, rows, count, graph_data, error_message)

    def _batch_progress(self, simulation_number: int, total: int, completed: int) -> None:
        self.progress_bar.configure(maximum=total, value=simulation_number)
        self.status.set(f"Lote en ejecución · simulación {simulation_number}/{total} · completadas: {completed}")

    def _finished_batch(self, rows: list[dict[str, object]], requested: int,
                        graph_data: tuple[SimulationConfig, SimulationResult] | None,
                        error_message: str = "") -> None:
        self.batch_summaries = rows
        self.batch_graph_data = graph_data
        self.running = False
        self.batch_mode = False
        self.engine = None
        self.start_button.configure(state="normal")
        self.batch_button.configure(state="normal")
        self.pause_button.configure(state="disabled", text="⏸ PAUSAR")
        self.stop_button.configure(state="disabled")
        self.progress_bar.configure(maximum=max(1, requested), value=len(rows))
        self.export_batch_csv_button.configure(state="normal" if rows else "disabled")
        self.export_batch_pdf_button.configure(state="normal" if rows else "disabled")

        if rows:
            self.chart_widget.grid()
            self.live_report.grid_remove()
            self._draw_batch_summary(rows)
            self.status.set(f"Lote finalizado · {len(rows)}/{requested} simulaciones completas")
            layers_used = str(rows[0]["capas_mitigacion"])
            self._log(f"Lote listo: {len(rows)} simulaciones completas. Capas aplicadas: {layers_used}. Puedes guardar el CSV y el PDF.")
        else:
            self.export_batch_csv_button.pack_forget()
            self.export_batch_pdf_button.pack_forget()
            self.chart_widget.grid_remove()
            self.live_report.grid()
            self.status.set("Lote detenido sin simulaciones completas")
            self._set_live_report("No se completó ningún lote. Puedes volver a la configuración e intentarlo de nuevo.")

        if error_message:
            self._log(f"La ejecución por lotes se detuvo por un error: {error_message}")
            messagebox.showerror("Error en simulación por lotes", error_message)
        elif len(rows) < requested:
            self._log("Ejecución cancelada; solo se conservaron lotes completados.")

        if self.reset_pending:
            self.reset_pending = False
            self.after(0, self.reset)
        elif self.return_pending:
            self.return_pending = False
            self._show_explorer()

    def _draw_batch_summary(self, rows: list[dict[str, object]]) -> None:
        x = list(range(1, len(rows) + 1))
        plots = (
            (0, (("solicitudes_legitimas_totales", "Legítimas", PALETTE["green"]),
                 ("solicitudes_maliciosas_totales", "Maliciosas", PALETTE["danger"]),
                 ("solicitudes_procesadas_totales", "Procesadas", PALETTE["amber"])),
             "Solicitudes totales por simulación", "Solicitudes"),
            (1, (("cpu_estimada_max_pct", "CPU máxima", PALETTE["green"]),
                 ("ram_estimada_max_pct", "RAM máxima", PALETTE["amber"]),
                 ("saturacion_max_pct", "Saturación máxima", PALETTE["danger"])),
             "Recursos estimados máximos", "Porcentaje (%)"),
            (2, (("red_rx_promedio_mbps", "RX promedio", "#63b3ed"),
                 ("red_tx_promedio_mbps", "TX promedio", "#b794f4")),
             "Consumo estimado de red", "Mbps"),
            (3, (("latencia_promedio_ms", "Latencia promedio", PALETTE["amber"]),
                 ("latencia_max_ms", "Latencia máxima", PALETTE["danger"])),
             "Latencia estimada", "Milisegundos (ms)"),
        )
        for index, series, title, ylabel in plots:
            axis = self.axes[index]
            axis.clear()
            axis.set_facecolor(PALETTE["panel"])
            axis.set_title(title, color=PALETTE["green"])
            axis.set_ylabel(ylabel, color=PALETTE["muted"])
            axis.set_xlabel("Simulación", color=PALETTE["muted"])
            for field, label, color in series:
                axis.plot(x, [float(row[field]) for row in rows], marker="o", linewidth=1.7, label=label, color=color)
            if len(rows) <= 20:
                axis.set_xticks(x, [str(row["id_simulacion"]).split("-")[-1] for row in rows], rotation=45)
            axis.tick_params(colors=PALETTE["muted"], labelsize=8)
            axis.grid(alpha=0.2, color=PALETTE["muted"])
            axis.legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8)
            for spine in axis.spines.values():
                spine.set_color("#315a48")
        self.figure.tight_layout(pad=2.0)
        self.canvas.draw_idle()

    def _run_worker(self):
        assert self.engine is not None
        result = self.engine.run(on_sample=lambda sample: self.after(0, self._on_sample, sample), on_event=lambda event: self.after(0, self._log, event))
        self.after(0, self._finished, result)

    def _on_sample(self, sample: SimulationSample):
        self.samples.append(sample)
        self._print_console_sample(sample)
        self._draw()
        config = self.active_config or self._config()
        duration = config.duration_seconds
        self.status.set(
            f"Exploración en ejecución · {config.scenario} · {self._duration_display(sample.second, duration)} · {sample.state}"
            f" · Legítimos: {sample.users_legitimate:,} · Maliciosos: {sample.users_suspicious:,}"
            f" · Cola: {sample.requests_queued:,.0f} · Rechazadas: {sample.requests_dropped:,.0f}"
        )
        self.progress_bar.configure(maximum=duration, value=sample.second)
        self._set_live_report(self._format_live_report(sample))

    def _start_console_table(self, config: SimulationConfig) -> None:
        self.console_table_active = sys.stdout is not None
        if not self.console_table_active:
            return
        try:
            print("\nSOLICITUDES POR SEGUNDO (valores del modelo local)", flush=True)
            print("Tiempo | Usuarios_leg | Req_leg/s | Usuarios_mal | Req_mal/s | Req_total/s | Req_atend/s | En_cola | Rechazadas | Usuarios_bloq", flush=True)
            print("-------+--------------+-----------+--------------+-----------+-------------+-------------+---------+------------+--------------", flush=True)
            initial_requests = config.initial_users * config.requests_per_user
            print(
                f"00:00  | {config.initial_users:12d} | {initial_requests:9.2f} | {0:12d} | {0.0:9.2f} | "
                f"{initial_requests:11.2f} | {initial_requests:11.2f} | {0:7.2f} | {0:10.2f} | {0:12d}",
                flush=True,
            )
        except (OSError, UnicodeError):
            self.console_table_active = False

    def _print_console_sample(self, sample: SimulationSample) -> None:
        if not self.console_table_active:
            return
        served = sample.processed_requests_s + sample.requests_cache
        minutes, seconds = divmod(sample.second, 60)
        elapsed = f"{minutes:02d}:{seconds:02d}"
        try:
            print(
                f"{elapsed:>6} | "
                f"{sample.users_legitimate:12d} | {sample.legitimate_requests_s:9.2f} | "
                f"{sample.users_suspicious:12d} | {sample.malicious_requests_s:9.2f} | "
                f"{sample.requests_generated:11.2f} | {served:11.2f} | "
                f"{sample.requests_queued:7.2f} | {sample.requests_dropped:10.2f} | {sample.users_blocked:12d}",
                flush=True,
            )
        except (OSError, UnicodeError):
            self.console_table_active = False

    def _finished(self, result: SimulationResult):
        self.result = result
        if self.console_table_active:
            print("Fin de la tabla de muestras.\n", flush=True)
            self.console_table_active = False
        self.running = False
        self.paused = False
        config = self.active_config or self._config()
        self.start_button.configure(state="normal")
        self.pause_button.configure(state="disabled", text="⏸ PAUSAR")
        self.stop_button.configure(state="disabled")
        self.batch_button.configure(state="normal")
        if len(result.samples) < config.duration_seconds:
            self.status.set(f"Exploración detenida · {self._duration_display(len(result.samples), config.duration_seconds)}")
        else:
            self.status.set(f"Exploración finalizada · {self._duration_display(len(result.samples), config.duration_seconds)} · Saturación máxima: {result.max_saturation:.1f}%")
        self.progress_bar.configure(maximum=max(1, config.duration_seconds), value=len(result.samples))
        self._set_live_report(
            "RESULTADO FINAL\n\n"
            f"Semilla utilizada: {config.seed}\n\n"
            f"Saturación máxima: {result.max_saturation:.1f}%\n"
            f"Tiempo en saturación: {result.time_saturated} s\n"
            f"Evaluación: {result.capacity_conclusion}\n"
            f"Detección: {result.detected_at if result.detected_at is not None else 'No detectada'}\n"
            f"Mitigación: {result.mitigation_at if result.mitigation_at is not None else 'No activada'}\n"
            f"Recuperación: {result.recovery_at if result.recovery_at is not None else 'No alcanzada'}\n\n"
            "CPU, RAM, solicitudes y saturación son estimaciones del modelo, no mediciones del servidor durante esta simulación.\n"
            "El perfil SSH es una captura de referencia; la telemetría real se consulta aparte en TELEMETRÍA SSH.\n"
            "SIMULATED_COLLAPSE no significa que el servidor real haya caído."
        )
        if result.samples:
            self.export_single_pdf_button.pack(side="left", padx=6)
        self._log("Exploración finalizada.")
        if self.reset_pending:
            self.reset_pending = False
            self.after(0, self.reset)
        elif self.return_pending:
            self.return_pending = False
            self._show_explorer()

    def _show_results_dashboard(self):
        """Abre un tablero final con indicadores y series de la simulación."""
        if not self.result or not self.result.samples:
            return

        config = self.active_config or self._config()

        window = tk.Toplevel(self)
        window.title("Dashboard de resultados | Simulador de resiliencia")
        window.geometry("1180x820")
        window.minsize(900, 650)
        window.configure(bg=PALETTE["panel"])
        window.columnconfigure(0, weight=1)

        ttk.Label(window, text="RESULTADOS DE LA SIMULACIÓN", style="Title.TLabel").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 4)
        )
        ttk.Label(
            window,
            text=f"Escenario: {config.scenario} · Duración: {self._duration_display(len(self.result.samples), config.duration_seconds)} · Capas seleccionadas: {', '.join(config.mitigation.selected) or 'ninguna'}. Indicadores estimados por el modelo local, no mediciones del servidor real.",
            wraplength=1100,
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 12))

        result = self.result
        samples = result.samples
        max_cpu = max(sample.cpu_percent for sample in samples)
        max_ram = max(sample.ram_percent for sample in samples)
        max_latency = max(sample.latency_ms for sample in samples)
        final_state = samples[-1].state
        kpis = (
            ("Saturación máxima", f"{result.max_saturation:.1f}%"),
            ("CPU máxima", f"{max_cpu:.1f}%"),
            ("RAM máxima", f"{max_ram:.1f}%"),
            ("Detección", f"{result.detected_at}s" if result.detected_at is not None else "No detectada"),
            ("Recuperación", f"{result.recovery_at}s" if result.recovery_at is not None else "No alcanzada"),
            ("Latencia máxima", f"{max_latency:.1f} ms"),
            ("Pico de solicitudes en cola", f"{max(sample.requests_queued for sample in samples):,.0f}"),
            ("Rechazadas por cola llena", f"{sum(sample.requests_dropped for sample in samples):,.0f}"),
            ("Estado final", final_state),
        )
        assessment = ttk.LabelFrame(window, text="Conclusión para este escenario", padding=(14, 8))
        assessment.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 6))
        ttk.Label(
            assessment, text=result.capacity_conclusion, style="Title.TLabel",
            wraplength=1100, justify="left",
        ).pack(anchor="w")
        cards = ttk.Frame(window)
        cards.grid(row=3, column=0, sticky="new", padx=18)
        for column in range(3):
            cards.columnconfigure(column, weight=1)
        for index, (label, value) in enumerate(kpis):
            card = ttk.LabelFrame(cards, text=label, padding=(12, 8))
            card.grid(row=index // 3, column=index % 3, sticky="ew", padx=5, pady=5)
            ttk.Label(card, text=value, style="Title.TLabel").pack(anchor="w")

        chart_frame = ttk.Frame(window)
        chart_frame.grid(row=4, column=0, sticky="nsew", padx=18, pady=(8, 12))
        window.rowconfigure(4, weight=1)
        figure = Figure(figsize=(11, 7), dpi=100, facecolor=PALETTE["panel"])
        axes = [figure.add_subplot(2, 2, index) for index in range(1, 5)]
        capacity_model = CapacityModel(self.profile, config)
        initial_requests, initial_cpu, initial_ram, initial_saturation, initial_rx, initial_tx = self._initial_chart_values(config, capacity_model)
        x = [0] + [sample.second for sample in samples]
        request_capacity = capacity_model.estimate().estimated_requests_per_second
        axes[0].set_title("Demanda y respuesta del sistema", color=PALETTE["green"])
        malicious_series = [0.0] + [s.malicious_requests_s for s in samples]
        axes[0].fill_between(x, 0, malicious_series, color=PALETTE["danger"], alpha=0.24, linewidth=0, zorder=1)
        self._plot_series(axes[0], x, [initial_requests] + [s.legitimate_requests_s for s in samples], label="Trafico legitimo", color=PALETTE["green"])
        self._plot_series(axes[0], x, malicious_series, label="Trafico malicioso simulado", color=PALETTE["danger"])
        self._plot_series(axes[0], x, [initial_requests] + [s.processed_requests_s + s.requests_cache for s in samples], label="Solicitudes atendidas", color=PALETTE["amber"])
        self._plot_series(axes[0], x, [request_capacity] + [s.capacity_rps for s in samples], label="Capacidad orientativa", color="#63b3ed", linestyle="--", linewidth=1.2)
        axes[0].set_ylabel("Solicitudes/s", color=PALETTE["muted"])
        axes[0].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8, ncol=2)
        axes[1].set_title("Recursos estimados del servidor", color=PALETTE["green"])
        self._plot_series(axes[1], x, [initial_cpu] + [s.cpu_percent for s in samples], label="CPU", color=PALETTE["green"])
        self._plot_series(axes[1], x, [initial_ram] + [s.ram_percent for s in samples], label="RAM", color=PALETTE["amber"])
        axes[1].axhline(100, color=PALETTE["danger"], linestyle="--", label="Limite modelado")
        axes[1].set_ylabel("Uso (%)", color=PALETTE["muted"])
        axes[1].set_ylim(0, 105)
        axes[1].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8, ncol=3)
        axes[2].set_title("Consumo estimado de red", color=PALETTE["green"])
        self._plot_series(axes[2], x, [initial_rx] + [s.network_rx_mbps for s in samples], label="Entrada al servidor (RX)", color="#63b3ed")
        self._plot_series(axes[2], x, [initial_tx] + [s.network_tx_mbps for s in samples], label="Respuesta del servidor (TX)", color=PALETTE["amber"])
        axes[2].set_ylabel("Mbps estimados", color=PALETTE["muted"])
        axes[2].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8)
        axes[3].set_title("Estabilidad y recuperacion", color=PALETTE["green"])
        self._plot_series(axes[3], x, [initial_saturation] + [s.saturation_percent for s in samples], label="Saturacion", color=PALETTE["green"], linewidth=2)
        axes[3].axhline(config.high_load_threshold, color=PALETTE["amber"], linestyle="--", label="Carga alta")
        axes[3].axhline(SATURATION_NEAR_LIMIT, color="#f6ad55", linestyle="--", label="Cerca del limite (75%)")
        axes[3].axhline(config.saturated_threshold, color=PALETTE["danger"], linestyle="--", label="Umbral de saturacion")
        for second, label, color in ((result.detected_at, "Deteccion", "#63b3ed"), (result.mitigation_at, "Mitigacion", "#b794f4"), (result.recovery_at, "Recuperacion", "#f6e58d")):
            if second is not None:
                axes[3].axvline(second, color=color, linestyle=":", label=f"{label} · {second}s")
        axes[3].set_ylabel("Saturacion (%)", color=PALETTE["muted"])
        axes[3].set_ylim(0, 105)
        axes[3].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8, ncol=2)
        for axis in axes:
            axis.set_facecolor(PALETTE["panel"])
            self._format_time_axis(axis, len(samples), config.start_hour)
            axis.xaxis.label.set_color(PALETTE["muted"])
            axis.tick_params(colors=PALETTE["muted"], labelsize=8)
            axis.grid(alpha=0.2, color=PALETTE["muted"])
            for spine in axis.spines.values():
                spine.set_color("#315a48")
        figure.tight_layout(pad=2.0)
        canvas = FigureCanvasTkAgg(figure, master=chart_frame)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        window.chart_interactions = self._install_chart_interactions(figure, axes, canvas)
        window.dashboard_canvas = canvas
        window.dashboard_figure = figure

        actions = ttk.Frame(window)
        actions.grid(row=5, column=0, sticky="e", padx=18, pady=(0, 16))
        ttk.Button(actions, text="Generar reporte TXT", command=self.save_report).pack(side="left", padx=5)
        ttk.Button(actions, text="Exportar PDF", command=self.save_pdf).pack(side="left", padx=5)
        ttk.Button(actions, text="Ver fuentes por hora", command=self._show_client_hourly).pack(side="left", padx=5)
        ttk.Button(actions, text="Exportar CSV", command=self.save_csv).pack(side="left", padx=5)
        ttk.Button(actions, text="Cerrar", command=window.destroy).pack(side="left", padx=5)

    def _show_client_hourly(self):
        if not self.result or not self.result.client_hourly:
            messagebox.showinfo("Sin detalle de clientes", "Esta simulacion no genero filas de detalle por cliente.")
            return
        window = tk.Toplevel(self)
        window.title("Solicitudes y consumo de red por hora")
        window.geometry("1240x620")
        window.minsize(960, 460)
        window.configure(bg=PALETTE["panel"])
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        ttk.Label(
            window,
            text="El consumo RX/TX es estimado con tamanos promedio por servicio. Direcciones y puertos son sinteticos; la deteccion por fuente es aproximada.",
            wraplength=1180,
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=12)
        columns = ("hour", "client", "origin", "service", "kind", "requests", "rx", "tx", "detected", "blocked", "granularity")
        tree = ttk.Treeview(window, columns=columns, show="headings")
        headings = {
            "hour": "Hora simulada", "client": "Cliente", "origin": "Origen IP:puerto",
            "service": "Servicio destino", "kind": "Tipo", "requests": "Solicitudes",
            "rx": "Entrada Mbps", "tx": "Salida Mbps", "granularity": "Detalle",
            "detected": "Detectada", "blocked": "Bloqueada",
        }
        for column, heading in headings.items():
            tree.heading(column, text=heading)
            tree.column(column, width=112, minwidth=80, stretch=True, anchor="w")
        tree.column("requests", anchor="e", width=95)
        tree.column("rx", anchor="e", width=100)
        tree.column("tx", anchor="e", width=100)
        tree.grid(row=1, column=0, sticky="nsew", padx=(14, 0), pady=(0, 12))
        vertical = ttk.Scrollbar(window, orient="vertical", command=tree.yview)
        vertical.grid(row=1, column=1, sticky="ns", padx=(0, 14), pady=(0, 12))
        tree.configure(yscrollcommand=vertical.set)
        horizontal = ttk.Scrollbar(window, orient="horizontal", command=tree.xview)
        horizontal.grid(row=2, column=0, sticky="ew", padx=14)
        tree.configure(xscrollcommand=horizontal.set)
        rows = sorted(self.result.client_hourly, key=lambda item: item.requests, reverse=True)[:1000]
        for item in rows:
            tree.insert("", "end", values=(
                f"D{item.simulation_day} {item.hour_of_day:02d}:00",
                item.client_id, f"{item.source_ip}:{item.source_port}",
                f"{item.service_name}:{item.service_port}/{item.service_protocol}",
                item.traffic_class, item.requests, f"{item.inbound_average_mbps:.4f}",
                f"{item.outbound_average_mbps:.4f}", "Si" if item.source_detected else "No",
                "Si" if item.source_blocked else "No", item.granularity,
            ))
    def pause(self):
        if not self.engine or not self.running:
            return
        if not self.paused:
            self.engine.pause()
            self.paused = True
            self.pause_button.configure(text="CONTINUAR")
            self.status.set("Exploracion pausada")
        else:
            self.engine.resume()
            self.paused = False
            self.pause_button.configure(text="PAUSAR")
            config = self.active_config or self._config()
            self.status.set(f"Exploración en ejecución · {config.scenario} · {self._duration_display(len(self.samples), config.duration_seconds)}")

    def _duration_display(self, elapsed_seconds, total_seconds):
        def clock(value):
            minutes, seconds = divmod(max(0, int(value)), 60)
            return f"{minutes:02d}:{seconds:02d}"
        return f"{clock(elapsed_seconds)} / {clock(total_seconds)}"

    def stop(self):
        if self.batch_mode:
            self.batch_stop_event.set()
            if self.engine:
                self.engine.stop()
            self.status.set("Deteniendo la simulación por lotes…")
            return
        if self.engine and self.running:
            self.engine.stop()
            self.status.set("Deteniendo exploración…")

    def return_to_explorer(self):
        if self.running:
            self.return_pending = True
            self.stop()
            return
        self._show_explorer()

    def _show_explorer(self):
        self.right_panel.grid_remove()
        self.controls_panel.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=(0, 10))

    def reset(self):
        if self.running:
            self.reset_pending = True
            self.stop()
            self.status.set("Deteniendo antes de reiniciar…")
            return
        self.samples = []
        self.result = None
        self.batch_summaries = []
        self.batch_graph_data = None
        self.export_single_pdf_button.pack_forget()
        self.export_batch_csv_button.pack_forget()
        self.export_batch_pdf_button.pack_forget()
        self.progress_bar.configure(maximum=100, value=0)
        self._draw_empty()
        self.chart_widget.grid_remove()
        self._show_explorer()
        self.stop_button.configure(state="disabled")
        self._set_live_report("INFORME EN TIEMPO REAL\n\nLa simulación se reinició. No hay datos activos.")
        self.status.set("Sin simulación activa")

    def _format_live_report(self, sample: SimulationSample) -> str:
        config = self.active_config or self._config()
        return (
            "INFORME EN TIEMPO REAL | SIMULACION LOCAL\n"
            f"Segundo: {sample.second} s\n"
            f"Servicio y puerto modelados: {config.service_name} | {config.service_port}/{config.service_protocol}\n"
            f"Perfil de demanda legítima: {config.legitimate_profile}\n"
            f"Estado: {sample.state} | Puntuacion de anomalia: {sample.anomaly_score:.1f}/100\n\n"
            "CARGA DE USUARIOS\n"
            f"Generados: {sample.users_generated:,} | Legitimos estimados: {sample.users_legitimate:,} | "
            f"Sospechosos: {sample.users_suspicious:,} | Bloqueados: {sample.users_blocked:,}\n\n"
            "SOLICITUDES\n"
            f"Generadas: {sample.requests_generated:,.1f} solicitudes/s\n"
            f"Procesadas por el modelo: {sample.processed_requests_s:,.1f} solicitudes/s\n"
            f"En cola: {sample.requests_queued:,.1f} | Rechazadas por desbordamiento: {sample.requests_dropped:,.1f}\n"
            f"Limitadas: {sample.requests_limited:,.1f} | Bloqueadas: {sample.requests_blocked:,.1f} | "
            f"Challenge: {sample.requests_challenge:,.1f}\n\n"
            "RECURSOS ESTIMADOS DEL SERVIDOR\n"
            f"CPU: {sample.cpu_percent:.1f}% | RAM: {sample.ram_percent:.1f}%\n"
            f"Consumo estimado de red RX/TX: {sample.network_rx_mbps:.3f}/{sample.network_tx_mbps:.3f} Mbps\n"
            f"Saturacion: {sample.saturation_percent:.1f}% | Latencia: {sample.latency_ms:.1f} ms\n"
            f"Capacidad orientativa: {sample.capacity_rps:,.1f} solicitudes/s | Instancias: {sample.instances}\n\n"
            "Lectura: CPU/RAM/saturación y consumo de red son estimaciones del modelo; no son telemetría del servidor."
        )
    def _set_live_report(self, value: str) -> None:
        self.live_report.configure(state="normal")
        self.live_report.delete("1.0", tk.END)
        self.live_report.insert("1.0", value)
        self.live_report.configure(state="disabled")

    @staticmethod
    def _format_time_axis(axis, duration_seconds: int, start_hour: int = 0) -> None:
        if duration_seconds >= 3600:
            axis.xaxis.set_major_formatter(FuncFormatter(
                lambda value, _position: SimulatorView._format_clock_tick(value, start_hour)
            ))
            axis.set_xlabel("Hora local simulada (HH:MM)")
        else:
            axis.set_xlabel("Tiempo (s)")

    @staticmethod
    def _format_clock_tick(value: float, start_hour: int) -> str:
        total = max(0, int(value)) + start_hour * 3600
        day = total // 86400 + 1
        hour = (total // 3600) % 24
        minute = (total % 3600) // 60
        return f"D{day} {hour:02d}:{minute:02d}" if day > 1 else f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _initial_chart_values(config: SimulationConfig, model: CapacityModel) -> tuple[float, float, float, float, float, float]:
        """Baseline at t=0, before the modeled attack begins."""
        users = config.initial_users
        requests = model.requests_per_second(users)
        cpu, ram, saturation = model.resource_usage(users, requests)
        rx, tx = model.network_consumption_mbps(requests, requests)
        return requests, cpu, ram, saturation, rx, tx
    def _install_chart_interactions(self, figure, axes, canvas):
        state = {
            "axes": axes,
            "positions": [axis.get_position().frozen() for axis in axes],
            "maximized": None,
            "annotations": [],
            "markers": [],
            "last_hover": None,
        }
        canvas.mpl_connect("button_press_event", lambda event: self._on_chart_click(event, state, canvas))
        canvas.mpl_connect("motion_notify_event", lambda event: self._on_chart_motion(event, state, canvas))
        self._refresh_chart_annotations(state)
        return state

    @staticmethod
    def _refresh_chart_annotations(state):
        annotations = []
        markers = []
        for axis in state["axes"]:
            annotation = axis.annotate(
                "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
                bbox={"boxstyle": "round,pad=0.4", "fc": "#0f1916", "ec": "#63b3ed", "alpha": 0.96},
                arrowprops={"arrowstyle": "->", "color": "#63b3ed"},
                color=PALETTE["text"], fontsize=9, zorder=20,
            )
            annotation.set_visible(False)
            annotations.append(annotation)
            marker = axis.scatter([], [], s=48, color="#f6e58d", edgecolors="#0f1916", zorder=21)
            marker.set_visible(False)
            markers.append(marker)
        state["annotations"] = annotations
        state["markers"] = markers

    @staticmethod
    def _plot_series(axis, x_values, y_values, **style):
        (line,) = axis.plot(x_values, y_values, **style)
        line.set_picker(8)
        line._simulator_hoverable = True
        return line

    def _on_chart_click(self, event, state, canvas):
        if event.button != 1:
            return
        maximized = state["maximized"]
        if event.dblclick:
            if maximized is not None:
                for axis, position in zip(state["axes"], state["positions"]):
                    axis.set_visible(True)
                    axis.set_position(position)
                state["maximized"] = None
                state["last_hover"] = None
                canvas.draw_idle()
            return
        if maximized is not None or event.inaxes not in state["axes"]:
            return
        selected = event.inaxes
        for axis in state["axes"]:
            axis.set_visible(axis is selected)
        selected.set_position([0.075, 0.12, 0.89, 0.80])
        state["maximized"] = selected
        state["last_hover"] = None
        canvas.draw_idle()

    def _on_chart_motion(self, event, state, canvas):
        annotations = state["annotations"]
        for annotation in annotations:
            annotation.set_visible(False)
        for marker in state["markers"]:
            marker.set_visible(False)
        axis = event.inaxes
        if axis not in state["axes"] or event.x is None or event.y is None:
            state["last_hover"] = None
            canvas.draw_idle()
            return
        if state["maximized"] is not None and axis is not state["maximized"]:
            return

        best = None
        for line in axis.get_lines():
            if not getattr(line, "_simulator_hoverable", False):
                continue
            hit, details = line.contains(event)
            if not hit:
                continue
            x_values, y_values = line.get_data()
            for index in details.get("ind", ()):
                if index >= len(x_values) or index >= len(y_values):
                    continue
                px, py = axis.transData.transform((x_values[index], y_values[index]))
                distance = (px - event.x) ** 2 + (py - event.y) ** 2
                if best is None or distance < best[0]:
                    best = (distance, line, index, x_values[index], y_values[index])

        if best is None:
            state["last_hover"] = None
            canvas.draw_idle()
            return
        _, line, index, x_value, y_value = best
        axis_index = state["axes"].index(axis)
        annotation = annotations[axis_index]
        unit = ("solicitudes/s", "%", "Mbps", "%")[axis_index]
        annotation.xy = (x_value, y_value)
        annotation.set_text(f"{line.get_label()}\n{float(y_value):,.2f} {unit}\nt = {float(x_value):.0f} s")
        annotation.set_visible(True)
        marker = state["markers"][axis_index]
        marker.set_offsets([[x_value, y_value]])
        marker.set_visible(True)
        state["last_hover"] = (id(line), index, float(x_value), float(y_value))
        canvas.draw_idle()

    def _draw_empty(self):
        titles = (
            "Demanda y respuesta del sistema (solicitudes/s)",
            "Recursos estimados del servidor (%)",
            "Consumo estimado de red (Mbps)",
            "Estabilidad y recuperacion (%)",
        )
        for axis, title in zip(self.axes, titles):
            axis.clear()
            axis.set_title(title, color=PALETTE["green"], fontsize=10, pad=8)
            axis.tick_params(colors=PALETTE["muted"], labelsize=8)
            axis.set_facecolor(PALETTE["panel"])
            axis.set_xlabel("Tiempo (s)", color=PALETTE["muted"], fontsize=8)
            axis.grid(alpha=0.18, color=PALETTE["muted"])
            for spine in axis.spines.values():
                spine.set_color("#315a48")
            if not self.samples:
                axis.text(0.5, 0.5, "Inicia una exploracion para ver datos", transform=axis.transAxes,
                          ha="center", va="center", color=PALETTE["muted"], fontsize=9)
        self.axes[0].set_ylabel("Solicitudes/s", color=PALETTE["muted"], fontsize=8)
        self.axes[1].set_ylabel("Uso (%)", color=PALETTE["muted"], fontsize=8)
        self.axes[1].set_ylim(0, 105)
        self.axes[2].set_ylabel("Mbps estimados", color=PALETTE["muted"], fontsize=8)
        self.axes[3].set_ylabel("Saturacion (%)", color=PALETTE["muted"], fontsize=8)
        self.axes[3].set_ylim(0, 105)
        if hasattr(self, "chart_interactions"):
            self._refresh_chart_annotations(self.chart_interactions)
        self.canvas.draw_idle()
    def _draw(self):
        if not self.samples:
            return
        self._draw_empty()
        config = self.active_config or self._config()
        model = CapacityModel(self.profile, config)
        initial_requests, initial_cpu, initial_ram, initial_saturation, initial_rx, initial_tx = self._initial_chart_values(config, model)
        x = [0] + [sample.second for sample in self.samples]
        request_capacity = model.estimate().estimated_requests_per_second
        load_series = (
            ("Trafico legitimo", [initial_requests] + [s.legitimate_requests_s for s in self.samples], PALETTE["green"]),
            ("Trafico malicioso simulado", [0.0] + [s.malicious_requests_s for s in self.samples], PALETTE["danger"]),
            ("Solicitudes atendidas", [initial_requests] + [s.processed_requests_s + s.requests_cache for s in self.samples], PALETTE["amber"]),
        )
        self.axes[0].fill_between(x, 0, load_series[1][1], color=PALETTE["danger"], alpha=0.24, linewidth=0, zorder=1)
        for label, values, color in load_series:
            self._plot_series(self.axes[0], x, values, label=label, color=color, linewidth=1.8)
        self._plot_series(self.axes[0], x, [request_capacity] + [s.capacity_rps for s in self.samples],
                          label="Capacidad orientativa", color="#63b3ed", linestyle="--", linewidth=1.2)
        self.axes[0].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8, ncol=2)
        for label, values, color in (
            ("CPU", [initial_cpu] + [s.cpu_percent for s in self.samples], PALETTE["green"]),
            ("RAM", [initial_ram] + [s.ram_percent for s in self.samples], PALETTE["amber"]),
        ):
            self._plot_series(self.axes[1], x, values, label=label, color=color, linewidth=1.8)
        self.axes[1].axhline(100, color=PALETTE["danger"], linestyle="--", linewidth=1, label="Limite modelado")
        self.axes[1].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8, ncol=3)
        self._plot_series(self.axes[2], x, [initial_rx] + [s.network_rx_mbps for s in self.samples],
                          label="Entrada al servidor (RX)", color="#63b3ed", linewidth=1.8)
        self._plot_series(self.axes[2], x, [initial_tx] + [s.network_tx_mbps for s in self.samples],
                          label="Respuesta del servidor (TX)", color=PALETTE["amber"], linewidth=1.8)
        self.axes[2].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8)
        self._plot_series(self.axes[3], x, [initial_saturation] + [s.saturation_percent for s in self.samples],
                          label="Saturacion", color=PALETTE["green"], linewidth=2)
        self.axes[3].axhline(config.high_load_threshold, color=PALETTE["amber"], linestyle="--", linewidth=1,
                             label=f"Carga alta ({config.high_load_threshold:g}%)")
        self.axes[3].axhline(SATURATION_NEAR_LIMIT, color="#f6ad55", linestyle="--", linewidth=1,
                             label=f"Cerca del limite ({SATURATION_NEAR_LIMIT:g}%)")
        self.axes[3].axhline(config.saturated_threshold, color=PALETTE["danger"], linestyle="--", linewidth=1,
                             label=f"Saturacion ({config.saturated_threshold:g}%)")
        if self.result:
            events = ((self.result.detected_at, "Deteccion", "#63b3ed"),
                      (self.result.mitigation_at, "Mitigacion", "#b794f4"),
                      (self.result.recovery_at, "Recuperacion", "#f6e58d"))
        else:
            detected_at = next((s.second for s in self.samples if "DETECTADA" in s.state or s.state.startswith("MITIGACI") or s.state == "RECUPERADO"), None)
            mitigation_at = next((s.second for s in self.samples if s.state.startswith("MITIGACI") or s.state == "RECUPERADO"), None)
            recovery_at = next((s.second for s in self.samples if s.state == "RECUPERADO"), None)
            events = ((detected_at, "Deteccion", "#63b3ed"),
                      (mitigation_at, "Mitigacion", "#b794f4"),
                      (recovery_at, "Recuperacion", "#f6e58d"))
        for second, label, color in events:
            if second is not None:
                self.axes[3].axvline(second, color=color, linestyle=":", linewidth=1.4, label=f"{label} · {second}s")
        self.axes[3].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8, ncol=2)
        for axis in self.axes:
            self._format_time_axis(axis, len(self.samples), config.start_hour)
        self.figure.tight_layout(pad=1.8)
        if self.chart_interactions["maximized"] is None:
            self.chart_interactions["positions"] = [axis.get_position().frozen() for axis in self.axes]
        else:
            self.chart_interactions["maximized"].set_position([0.075, 0.12, 0.89, 0.80])
        self.canvas.draw_idle()
    def _log(self, text: str):
        self.event_log.configure(state="normal")
        self.event_log.insert("end", f"[{__import__('datetime').datetime.now():%H:%M:%S}] {text}\n")
        self.event_log.see("end")
        self.event_log.configure(state="disabled")

    def save_report(self):
        if not self.result or not self.profile:
            messagebox.showinfo("Sin resultados", "Ejecuta una simulación antes de generar el reporte.")
            return
        config = self.active_config or self._config()
        path = generate_report(self.profile, config, self.result, CapacityModel(self.profile, config), Path("datos/reportes"))
        messagebox.showinfo("Reporte generado", str(path))

    def save_batch_csv(self):
        if not self.batch_summaries:
            messagebox.showinfo("Sin lotes completados", "Ejecuta una simulación por lotes antes de exportar el CSV.")
            return
        filename = filedialog.asksaveasfilename(
            parent=self, title="Guardar dataframe de simulaciones", defaultextension=".csv",
            initialfile="simulaciones_del_lote.csv", filetypes=(("CSV", "*.csv"),),
        )
        if not filename:
            return
        try:
            path = export_batch_csv(self.batch_summaries, Path(filename))
        except OSError as error:
            messagebox.showerror("No se pudo guardar el CSV", str(error))
            return
        messagebox.showinfo("Dataframe exportado", f"Se exportaron {len(self.batch_summaries)} simulaciones completadas:\n{path}")

    def save_batch_pdf(self):
        if not self.batch_graph_data or not self.profile:
            messagebox.showinfo("Sin simulación completa", "Completa al menos una simulación del lote antes de exportar sus gráficas.")
            return
        config, result = self.batch_graph_data
        simulation_id = str(self.batch_summaries[0]["id_simulacion"])
        filename = filedialog.asksaveasfilename(
            parent=self, title="Guardar gráficas de la primera simulación", defaultextension=".pdf",
            initialfile="reporte_simulacion_1.pdf", filetypes=(("PDF", "*.pdf"),),
        )
        if not filename:
            return
        try:
            path = export_pdf(
                self.profile, config, result, CapacityModel(self.profile, config),
                Path(filename).parent, output_path=Path(filename),
            )
        except (OSError, ValueError) as error:
            messagebox.showerror("No se pudo generar el PDF", str(error))
            return
        messagebox.showinfo(
            "Gráficas exportadas",
            f"Se exportó el reporte normal con las gráficas temporales de {simulation_id}.\n{path}",
        )

    def save_csv(self):
        if not self.result or not self.result.samples:
            messagebox.showinfo("Sin resultados", "Ejecuta una simulación antes de exportar los datos.")
            return
        path = export_csv(self.result, Path("datos/reportes"), self.active_config)
        if self.result.client_hourly:
            detail_path = path.with_name(f"{path.stem}_clientes_por_hora.csv")
            messagebox.showinfo("CSV exportados", f"Serie por segundo:\n{path}\n\nDetalle por cliente y hora:\n{detail_path}")
        else:
            messagebox.showinfo("CSV exportado", str(path))

    def save_pdf(self):
        if not self.result or not self.profile:
            messagebox.showinfo("Sin resultados", "Ejecuta una simulación antes de exportar el PDF.")
            return
        config = self.active_config or self._config()
        filename = filedialog.asksaveasfilename(
            parent=self, title="Guardar gráficas de la exploración", defaultextension=".pdf",
            initialfile="reporte_simulacion.pdf", filetypes=(("PDF", "*.pdf"),),
        )
        if not filename:
            return
        try:
            path = export_pdf(
                self.profile, config, self.result, CapacityModel(self.profile, config),
                Path(filename).parent, output_path=Path(filename),
            )
        except (OSError, ValueError) as error:
            messagebox.showerror("No se pudo generar el PDF", str(error))
            return
        messagebox.showinfo("PDF exportado", f"Se guardaron el reporte y las gráficas de esta exploración:\n{path}")

    def open_live_telemetry(self) -> None:
        if not self.monitor_credentials:
            messagebox.showinfo("Sin conexión SSH", "La telemetría en vivo requiere un perfil obtenido por SSH. Los perfiles de demostración o JSON no tienen conexión activa.")
            return
        if self._telemetry_window is not None and self._telemetry_window.winfo_exists():
            self._telemetry_window.lift()
            return
        window = tk.Toplevel(self)
        self._telemetry_window = window
        stop_event = threading.Event()
        self._telemetry_stop = stop_event
        window.title("Telemetría real del servidor | Solo lectura")
        window.geometry("820x540")
        window.minsize(700, 420)
        window.configure(bg=PALETTE["panel"])
        window.columnconfigure(0, weight=1)
        window.rowconfigure(2, weight=1)
        ttk.Label(window, text="TELEMETRÍA SSH EN VIVO", style="Title.TLabel").grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        summary = tk.StringVar(value="Conectando…")
        ttk.Label(window, textvariable=summary, wraplength=780, justify="left").grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        tabs = ttk.Notebook(window)
        tabs.grid(row=2, column=0, sticky="nsew", padx=14, pady=4)
        process_frame = ttk.Frame(tabs)
        port_frame = ttk.Frame(tabs)
        comparison_frame = ttk.Frame(tabs)
        tabs.add(process_frame, text="Procesos")
        process_tabs = ttk.Notebook(process_frame)
        process_tabs.pack(fill="both", expand=True)
        real_process_frame = ttk.Frame(process_tabs)
        virtual_bots_frame = ttk.Frame(process_tabs)
        process_tabs.add(real_process_frame, text="Procesos SSH + bots virtuales")
        process_tabs.add(virtual_bots_frame, text="Bots maliciosos simulados")
        tabs.add(port_frame, text="Puertos en escucha")
        tabs.add(comparison_frame, text="Real vs simulación")
        ttk.Label(real_process_frame, text="SSH real y bots virtuales se listan juntos. Las filas rojas SIMULADO no tienen PID ni consumo real en el servidor.", style="Subtitle.TLabel", wraplength=740).pack(anchor="w", padx=8, pady=(6, 3))
        columns = ("pid", "ppid", "name", "threads", "cpu", "mem", "rss", "origin_ip", "origin", "requests")
        ttk.Label(real_process_frame, text="Las filas SSH muestran valores medidos. Las filas rojas SIMULADO muestran CPU y memoria estimadas desde la gráfica; no son consumo físico.", style="Subtitle.TLabel", wraplength=740).pack(anchor="w", padx=8, pady=(0, 3))
        tree = ttk.Treeview(real_process_frame, columns=columns, show="headings", height=12)
        for key, title, width in (("pid", "PID / ID virtual", 90), ("ppid", "PID padre", 60), ("name", "Proceso", 135), ("threads", "Hilos", 50), ("cpu", "CPU %", 70), ("mem", "Memoria %", 80), ("rss", "RAM residente MB", 90), ("origin_ip", "IP de origen", 125), ("origin", "Origen", 80), ("requests", "Req/s simuladas", 105)):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        tree.tag_configure("malicious", background="#54252b", foreground="#ffe1e3")
        tree.tag_configure("real", background=PALETTE["panel"])
        tree.pack(fill="both", expand=True)
        process_scroll = ttk.Scrollbar(real_process_frame, orient="horizontal", command=tree.xview)
        process_scroll.pack(fill="x", side="bottom")
        tree.configure(xscrollcommand=process_scroll.set)
        ttk.Label(virtual_bots_frame, text="Entidades virtuales del modelo: no tienen PID real, no crean procesos y no envían tráfico ni consumen recursos del servidor.", style="Subtitle.TLabel", wraplength=740, justify="left").pack(anchor="w", padx=8, pady=(8, 4))
        bot_activity_info = tk.StringVar(value="Inicia la simulación para ver la actividad virtual de los bots.")
        ttk.Label(virtual_bots_frame, textvariable=bot_activity_info, style="Subtitle.TLabel").pack(anchor="w", padx=8, pady=(0, 4))
        bot_tree = ttk.Treeview(virtual_bots_frame, columns=("virtual_id", "ip", "requests"), show="headings", height=12)
        bot_tree.heading("virtual_id", text="Identificador virtual (no es PID)")
        bot_tree.heading("ip", text="IP de origen simulada")
        bot_tree.heading("requests", text="Solicitudes generadas/s · estimación")
        bot_tree.column("virtual_id", width=300, anchor="w")
        bot_tree.column("ip", width=180, anchor="w")
        bot_tree.column("requests", width=300, anchor="e")
        bot_tree.tag_configure("malicious", background="#54252b", foreground="#ffe1e3")
        bot_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        port_tree = ttk.Treeview(port_frame, columns=("listener",), show="headings", height=12)
        port_tree.heading("listener", text="Sockets TCP/UDP en escucha (salida de ss -lntup)")
        port_tree.column("listener", width=760, anchor="w")
        port_tree.pack(fill="both", expand=True)
        comparison_info = tk.StringVar(value="Real = servidor completo por SSH; simulado = estimación del servicio, sin enviar carga al servidor. La red real puede incluir otros servicios.")
        ttk.Label(comparison_frame, textvariable=comparison_info, style="Subtitle.TLabel", wraplength=740, justify="left").pack(anchor="w", padx=8, pady=(8, 4))
        comparison_figure = Figure(figsize=(7.8, 3.0), dpi=85, facecolor=PALETTE["panel"])
        comparison_axes = [comparison_figure.add_subplot(2, 2, index) for index in range(1, 5)]
        telemetry_chart = FigureCanvasTkAgg(comparison_figure, master=comparison_frame)
        telemetry_chart.get_tk_widget().pack(fill="x", expand=False, padx=6, pady=2)
        comparison_history = {"time": [], "cpu_real": [], "cpu_model": [], "ram_real": [], "ram_model": [],
                              "rx_real": [], "rx_model": [], "tx_real": [], "tx_model": [],
                              "legitimate": [], "malicious": []}
        telemetry_started_at = [None]
        comparison_tree = ttk.Treeview(comparison_frame, columns=("metric", "real", "model"), show="headings", height=6)
        for key, title, width in (("metric", "Indicador", 220), ("real", "Real · SSH", 230), ("model", "Simulado · modelo", 260)):
            comparison_tree.heading(key, text=title)
            comparison_tree.column(key, width=width, anchor="w")
        comparison_tree.tag_configure("malicious", background="#54252b", foreground="#ffe1e3")
        comparison_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        ttk.Label(window, text="Muestra de solo lectura cada 2 s. CPU y red se calculan entre muestras; la sesión no genera solicitudes al servicio.", style="Subtitle.TLabel", wraplength=780).grid(row=3, column=0, sticky="w", padx=14, pady=(4, 12))

        def close_window():
            stop_event.set()
            self._telemetry_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_window)

        def render(snapshot: dict):
            if stop_event.is_set() or not window.winfo_exists():
                return
            summary.set(
                f"{snapshot['timestamp']} · CPU {snapshot['cpu_percent']:.1f}% · "
                f"RAM disponible {snapshot['ram_available_mb']:.0f}/{snapshot['ram_total_mb']:.0f} MB · "
                f"Swap {snapshot['swap_used_mb']:.0f}/{snapshot['swap_total_mb']:.0f} MB ({snapshot['swap_percent']:.1f}%) · "
                f"Red RX/TX {snapshot['network_rx_mbps']:.3f}/{snapshot['network_tx_mbps']:.3f} Mbps"
            )
            for item in tree.get_children():
                tree.delete(item)
            for process in snapshot["processes"]:
                tree.insert("", "end", values=(process["pid"], process["ppid"], process["nombre"], process["hilos"], f"{process['cpu']:.1f}", f"{process['memoria_pct']:.1f}", f"{process['rss_mb']:.1f}", "—", "SSH real", "—"), tags=("real",))
            sample = self.samples[-1] if self.samples else None
            for item in bot_tree.get_children():
                bot_tree.delete(item)
            if sample:
                bot_activity_info.set(
                    f"Muestra simulada t={sample.second}s · {sample.users_suspicious:,} bots virtuales · "
                    f"{sample.malicious_requests_s:,.1f} solicitudes maliciosas/s generadas. Se muestran hasta 50 fuentes."
                )
                all_bot_rows = sorted(sample.malicious_bot_activity, key=lambda item: item[1], reverse=True)
                bot_rows = all_bot_rows[:50]
                if bot_rows and bot_rows[0][0] == 0:
                    bot_id = f"SIM-GRUPO-{sample.users_suspicious:,}"
                    display_rows = [(bot_id, bot_rows[0][1])]
                else:
                    display_rows = [(f"SIM-BOT-{bot_index:05d}", rate) for bot_index, rate in bot_rows]
                if all_bot_rows and all_bot_rows[0][0] != 0 and len(all_bot_rows) > 50:
                    remaining = all_bot_rows[49:]
                    display_rows = display_rows[:49] + [(f"SIM-RESTO-{len(remaining)}", sum(rate for _, rate in remaining))]
                request_total = max(sample.requests_generated, 1.0)
                for bot_id, requests_per_second in display_rows:
                    share = max(0.0, requests_per_second) / request_total
                    cpu_estimate = sample.cpu_percent * share
                    ram_estimate = sample.ram_percent * share
                    bot_rate = f"{requests_per_second:,.1f}"
                    if bot_id.startswith("SIM-BOT-"):
                        bot_index = int(bot_id.rsplit("-", 1)[1])
                        source_ip = SimulationEngine._synthetic_client_ip("Malicioso", bot_index)
                    else:
                        source_ip = "Varias IP simuladas"
                    cpu_text = f"{cpu_estimate:.3f}%"
                    ram_text = f"{ram_estimate:.3f}%"
                    bot_tree.insert("", "end", values=(bot_id, source_ip, bot_rate), tags=("malicious",))
                    tree.insert("", "end", values=(bot_id, "—", "Bot malicioso virtual", "—", cpu_text, ram_text, "No aplica", source_ip, "SIMULADO", bot_rate), tags=("malicious",))
            else:
                bot_activity_info.set("Todavía no hay muestras de simulación. Esta lista no representa procesos del sistema operativo.")
            for item in port_tree.get_children():
                port_tree.delete(item)
            for line in snapshot["listening_ports"]:
                port_tree.insert("", "end", values=(line,))
            if sample:
                comparison_info.set(f"Lectura SSH: {snapshot['timestamp']} · Última muestra simulada: t={sample.second}s ({sample.state}). La simulación no genera carga en el servidor.")
            else:
                comparison_info.set(f"Lectura SSH: {snapshot['timestamp']} · Aún no hay muestras de simulación para comparar.")
            real_ram_percent = (snapshot["ram_used_mb"] / snapshot["ram_total_mb"] * 100) if snapshot["ram_total_mb"] else 0.0
            history = comparison_history
            if telemetry_started_at[0] is None:
                telemetry_started_at[0] = snapshot["_time"]
            elapsed = snapshot["_time"] - telemetry_started_at[0]
            history["time"].append(elapsed)
            history["cpu_real"].append(snapshot["cpu_percent"])
            history["cpu_model"].append(sample.cpu_percent if sample else float("nan"))
            history["ram_real"].append(real_ram_percent)
            history["ram_model"].append(sample.ram_percent if sample else float("nan"))
            history["rx_real"].append(snapshot["network_rx_mbps"])
            history["rx_model"].append(sample.network_rx_mbps if sample else float("nan"))
            history["tx_real"].append(snapshot["network_tx_mbps"])
            history["tx_model"].append(sample.network_tx_mbps if sample else float("nan"))
            history["legitimate"].append(sample.legitimate_requests_s if sample else 0.0)
            history["malicious"].append(sample.malicious_requests_s if sample else 0.0)
            if len(history["time"]) > 120:
                for values in history.values():
                    del values[0]
            chart_specs = (
                ("CPU (%)", (("Real SSH", "cpu_real", PALETTE["blue"] if "blue" in PALETTE else "#63b3ed"), ("Simulada", "cpu_model", PALETTE["green"]))),
                ("RAM usada (%)", (("Real SSH", "ram_real", "#63b3ed"), ("Simulada", "ram_model", PALETTE["amber"]))),
                ("Red (Mbps)", (("RX real", "rx_real", "#63b3ed"), ("RX simulada", "rx_model", PALETTE["green"]), ("TX real", "tx_real", "#f6ad55"), ("TX simulada", "tx_model", PALETTE["amber"]))),
                ("Solicitudes simuladas (req/s)", (("Legítimas", "legitimate", PALETTE["green"]), ("Maliciosas", "malicious", PALETTE["danger"]))),
            )
            for axis, (title, plotted) in zip(comparison_axes, chart_specs):
                axis.clear()
                axis.set_facecolor(PALETTE["panel"])
                axis.set_title(title, color=PALETTE["green"], fontsize=9)
                axis.tick_params(colors=PALETTE["muted"], labelsize=7)
                axis.grid(alpha=0.18, color=PALETTE["muted"])
                for spine in axis.spines.values():
                    spine.set_color("#315a48")
                for label, series_key, color in plotted:
                    axis.plot(history["time"], history[series_key], label=label, color=color, linewidth=1.5)
                if title.startswith("Solicitudes"):
                    axis.fill_between(history["time"], 0, history["malicious"], color=PALETTE["danger"], alpha=0.3, linewidth=0)
                axis.set_xlabel("Tiempo de telemetría (s)", color=PALETTE["muted"], fontsize=7)
                axis.legend(frameon=False, fontsize=7, labelcolor=PALETTE["text"])
            comparison_figure.tight_layout(pad=1.2)
            telemetry_chart.draw_idle()
            rows = (
                ("CPU", f"{snapshot['cpu_percent']:.1f}%", f"{sample.cpu_percent:.1f}%" if sample else "Sin simulación"),
                ("RAM usada", f"{snapshot['ram_used_mb']:.0f} MB ({real_ram_percent:.1f}%)", f"{sample.ram_percent:.1f}% estimado" if sample else "Sin simulación"),
                ("Swap usada", f"{snapshot['swap_used_mb']:.0f}/{snapshot['swap_total_mb']:.0f} MB ({snapshot['swap_percent']:.1f}%)", "No modelado"),
                ("Red recibida (RX)", f"{snapshot['network_rx_mbps']:.3f} Mbps", f"{sample.network_rx_mbps:.3f} Mbps estimados" if sample else "Sin simulación"),
                ("Red enviada (TX)", f"{snapshot['network_tx_mbps']:.3f} Mbps", f"{sample.network_tx_mbps:.3f} Mbps estimados" if sample else "Sin simulación"),
                ("Solicitudes legítimas", "No se envían al servidor", f"{sample.legitimate_requests_s:.1f} req/s" if sample else "Sin simulación"),
                ("Solicitudes maliciosas", "No se envían al servidor", f"{sample.malicious_requests_s:.1f} req/s" if sample else "Sin simulación"),
                ("Saturación", "No es una métrica del sistema operativo", f"{sample.saturation_percent:.1f}% estimada" if sample else "Sin simulación"),
            )
            for item in comparison_tree.get_children():
                comparison_tree.delete(item)
            for metric, real_value, modeled_value in rows:
                tags = ("malicious",) if metric == "Solicitudes maliciosas" else ()
                comparison_tree.insert("", "end", values=(metric, real_value, modeled_value), tags=tags)

        def show_error(error: str):
            if not stop_event.is_set() and window.winfo_exists():
                summary.set(f"No se pudo leer la telemetría: {error}")

        def worker():
            credentials = self.monitor_credentials or {}
            manager = SSHManager(credentials["host"], int(credentials["port"]), credentials["username"], credentials.get("password", ""), credentials.get("key_file", ""))
            previous = None
            try:
                manager.connect()
                while not stop_event.is_set():
                    snapshot = manager.read_live_snapshot(previous)
                    previous = snapshot
                    self.after(0, render, snapshot)
                    if stop_event.wait(2.0):
                        break
            except (SSHConnectionError, OSError, ValueError) as error:
                self.after(0, show_error, str(error))
            finally:
                manager.close()

        threading.Thread(target=worker, daemon=True).start()

    def trace_route(self) -> None:
        if not self.monitor_credentials:
            return
        host = self.monitor_credentials["host"]
        window = tk.Toplevel(self)
        window.title(f"Ruta de red hacia {host}")
        window.geometry("760x500")
        window.configure(bg=PALETTE["panel"])
        ttk.Label(window, text=f"TRAZADO DESDE ESTE EQUIPO HASTA {host}", style="Title.TLabel").pack(anchor="w", padx=12, pady=10)
        output = tk.Text(window, bg="#0f1916", fg=PALETTE["text"], relief="flat", wrap="word", font=("Consolas", 10))
        output.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        output.insert("1.0", "Ejecutando diagnóstico de ruta…\nNo genera solicitudes al servicio; usa sondas de diagnóstico de red.")
        output.configure(state="disabled")

        def render(text: str):
            if not window.winfo_exists():
                return
            output.configure(state="normal")
            output.delete("1.0", tk.END)
            output.insert("1.0", text)
            output.configure(state="disabled")

        def worker():
            try:
                if sys.platform == "win32":
                    command = ["tracert", "-d", "-h", "12", "-w", "1000", host]
                else:
                    import shutil
                    binary = shutil.which("traceroute")
                    if binary:
                        command = [binary, "-n", "-m", "12", "-w", "1", host]
                    else:
                        binary = shutil.which("tracepath")
                        if not binary:
                            raise FileNotFoundError("Instala traceroute o tracepath para consultar la ruta desde este equipo.")
                        command = [binary, "-m", "12", host]
                completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
                result = completed.stdout.strip() or completed.stderr.strip() or f"El comando terminó con código {completed.returncode} sin salida."
                result += "\n\nLa ruta observada desde este equipo es contexto de conectividad; no mide la capacidad de aplicación ni el camino de entrada de todos los clientes."
            except (OSError, subprocess.TimeoutExpired) as error:
                result = f"No se pudo completar el trazado: {error}"
            self.after(0, render, result)

        threading.Thread(target=worker, daemon=True).start()
