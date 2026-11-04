from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from aplicacion.interfaz.componentes_interfaz import PALETTE
from aplicacion.modelos.perfil_servidor import ServerProfile
from aplicacion.modelos.configuracion_simulacion import MITIGATION_NAMES, MitigationConfig, SimulationConfig, preset
from aplicacion.reportes.generador_reportes import generate_report
from aplicacion.simulacion.modelo_capacidad import CapacityModel
from aplicacion.simulacion.motor_simulacion import SimulationEngine, SimulationResult, SimulationSample


class SimulatorView(ttk.Frame):
    def __init__(self, parent, on_back):
        super().__init__(parent)
        self.profile: ServerProfile | None = None
        self.engine: SimulationEngine | None = None
        self.result: SimulationResult | None = None
        self.running = False
        self.paused = False
        self.reset_pending = False
        self.return_pending = False
        self.active_config: SimulationConfig | None = None
        self.active_duration_unit = "Segundos"
        self.samples: list[SimulationSample] = []
        self.vars = {name: tk.StringVar(value=value) for name, value in {
            "initial": "20", "maximum": "1000", "duration": "60", "requests": "1.0", "request_bytes": "2048", "response_bytes": "16384", "latency": "200", "detect": "70", "sudden_ramp": "5", "intensity": "10000", "normal": "30", "detection_delay": "15", "bandwidth": "0", "rate_limit": "500", "cache_hit": "80", "edge_filter": "90", "anomaly_window": "3",
        }.items()}
        self.duration_unit = tk.StringVar(value="Segundos")
        self.scenario = tk.StringVar(value="Gradual")
        self.preset_name = tk.StringVar(value="Protección básica")
        self.layer_vars = {name: tk.BooleanVar(value=name == "Rate Limiting") for name in MITIGATION_NAMES}
        self.status = tk.StringVar(value="Sin simulación activa")
        self._build(on_back)

    def _build(self, on_back):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text="SIMULADOR DE RESILIENCIA", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(12, 8))
        ttk.Label(self, text="Explora un escenario a la vez y configura sus parámetros.", foreground=PALETTE["muted"]).grid(row=0, column=1, sticky="e", pady=(12, 8))
        controls = ttk.LabelFrame(self, text="EXPLORADOR INTERACTIVO (NO FACTORIAL)", padding=10)
        controls.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 10))
        self.controls_panel = controls
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(0, weight=1)
        controls_canvas = tk.Canvas(controls, highlightthickness=0, bg=PALETTE["panel"])
        controls_scrollbar = ttk.Scrollbar(controls, orient="vertical", command=controls_canvas.yview)
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_canvas.grid(row=0, column=0, sticky="nsew")
        controls_scrollbar.grid(row=0, column=1, sticky="ns")
        control_items = ttk.Frame(controls_canvas)
        control_window = controls_canvas.create_window((0, 0), window=control_items, anchor="nw")
        control_items.bind("<Configure>", lambda _event: controls_canvas.configure(scrollregion=controls_canvas.bbox("all")))
        controls_canvas.bind("<Configure>", lambda event: controls_canvas.itemconfigure(control_window, width=event.width))
        controls_canvas.bind("<Enter>", lambda _event: controls_canvas.bind_all("<MouseWheel>", lambda event: controls_canvas.yview_scroll(-1 * int(event.delta / 120), "units")))
        controls_canvas.bind("<Leave>", lambda _event: controls_canvas.unbind_all("<MouseWheel>"))
        controls = control_items
        for column in range(3):
            controls.columnconfigure(column, weight=1, uniform="parameter_groups")

        def add_field(parent, row, label, key):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=5)
            if key == "duration":
                duration_controls = ttk.Frame(parent)
                duration_controls.grid(row=row, column=1, sticky="ew", pady=5)
                ttk.Entry(duration_controls, textvariable=self.vars[key], width=7).pack(side="left", fill="x", expand=True)
                self.duration_combo = ttk.Combobox(duration_controls, textvariable=self.duration_unit, values=("Segundos", "Minutos"), state="readonly", width=10)
                self.duration_combo.pack(side="left", padx=(5, 0))
            else:
                ttk.Entry(parent, textvariable=self.vars[key], width=12).grid(row=row, column=1, sticky="ew", pady=5)
            parent.columnconfigure(1, weight=1)

        general = ttk.LabelFrame(controls, text="USUARIOS Y DURACIÓN", padding=10)
        general.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        general_fields = (("Usuarios iniciales", "initial"), ("Usuarios máximos", "maximum"), ("Duración", "duration"), ("Intensidad base (req/s)", "intensity"), ("Inicio ataque (s)", "normal"), ("Tiempo de detección (s)", "detection_delay"), ("Rampa repentina (s)", "sudden_ramp"))
        for row, (label, key) in enumerate(general_fields):
            add_field(general, row, label, key)
        ttk.Label(general, text="Escenario").grid(row=len(general_fields), column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Combobox(general, textvariable=self.scenario, values=("Gradual", "Repentino", "Pulsante", "Spike", "Personalizado"), state="readonly", width=14).grid(row=len(general_fields), column=1, sticky="ew", pady=5)

        traffic = ttk.LabelFrame(controls, text="TRÁFICO Y CAPACIDAD", padding=10)
        traffic.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        traffic_fields = (("Ancho banda Mbps (0=perfil)", "bandwidth"), ("Requests / usuario / s", "requests"), ("Bytes / request", "request_bytes"), ("Bytes / response", "response_bytes"), ("Latencia objetivo (ms)", "latency"), ("Umbral de anomalía %", "detect"))
        for row, (label, key) in enumerate(traffic_fields):
            add_field(traffic, row, label, key)

        defense = ttk.LabelFrame(controls, text="MITIGACIÓN", padding=10)
        defense.grid(row=0, column=2, sticky="nsew", padx=6, pady=6)
        ttk.Label(defense, text="Capas activas", foreground=PALETTE["green"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        layers = ttk.Frame(defense)
        layers.grid(row=1, column=0, columnspan=2, sticky="ew")
        for index, name in enumerate(MITIGATION_NAMES):
            tk.Checkbutton(layers, text=name, variable=self.layer_vars[name], bg=PALETTE["panel"], fg=PALETTE["text"], activebackground=PALETTE["panel"], activeforeground=PALETTE["green"], selectcolor="#1d4d38", anchor="w").grid(row=index, column=0, sticky="w", pady=1)
        ttk.Label(defense, text="Preset").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 5))
        preset_combo = ttk.Combobox(defense, textvariable=self.preset_name, values=("Protección básica", "Protección web", "Protección avanzada", "Alta disponibilidad", "Defensa multicapa"), state="readonly", width=18)
        preset_combo.grid(row=2, column=1, sticky="ew", pady=(10, 5))
        preset_combo.bind("<<ComboboxSelected>>", self._apply_preset)
        defense_fields = (("Límite req/s", "rate_limit"), ("Cache hit %", "cache_hit"), ("Edge filtrado %", "edge_filter"), ("Ventana de anomalía", "anomaly_window"))
        for row, (label, key) in enumerate(defense_fields, start=3):
            add_field(defense, row, label, key)

        self.start_button = ttk.Button(controls, text="INICIAR EXPLORACIÓN", command=self.start, style="Primary.TButton")
        self.start_button.grid(row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=(12, 4))
        ttk.Button(controls, text="VOLVER AL PERFIL", command=on_back).grid(row=2, column=0, columnspan=3, sticky="ew", padx=6, pady=(4, 2))
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
        ttk.Button(self.graph_actions, text="VOLVER AL EXPLORADOR INTERACTIVO", command=self.return_to_explorer).pack(side="right", padx=6)
        self.figure = Figure(figsize=(10, 7), dpi=100, facecolor=PALETTE["panel"])
        self.axes = [self.figure.add_subplot(3, 2, index) for index in range(1, 7)]
        self.figure.tight_layout(pad=2.5)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.chart_widget = self.canvas.get_tk_widget()
        self.chart_widget.grid(row=1, column=0, sticky="nsew")
        self.chart_widget.grid_remove()
        self.live_report = tk.Text(right, height=9, state="disabled", bg="#0f1916", fg=PALETTE["text"], relief="flat", font=("Consolas", 10), wrap="word")
        self.live_report.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.event_log = tk.Text(right, height=5, state="disabled", bg="#0f1916", fg="#89a79a", relief="flat", font=("Consolas", 10), wrap="word")
        self.event_log.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self._set_live_report("EXPLORACIÓN INTERACTIVA\n\nLos resultados se mostrarán aquí durante la simulación.")
        self._draw_empty()

    def set_profile(self, profile: ServerProfile):
        self.profile = profile
        estimate = CapacityModel(profile, self._config()).summary() if self._valid_config(show_error=False) else "Perfil listo. Configura la simulación."
        self._log(estimate)

    def _config(self) -> SimulationConfig:
        number = lambda key: float(self.vars[key].get())
        selected = tuple(name for name, variable in self.layer_vars.items() if variable.get())
        duration_seconds = int(number("duration")) * (60 if self.duration_unit.get() == "Minutos" else 1)
        mitigation = MitigationConfig(selected=selected, rate_limit_rps=number("rate_limit"), cdn_hit_ratio=number("cache_hit"), edge_filter_percent=number("edge_filter"), anomaly_threshold=number("detect"), anomaly_window_seconds=int(number("anomaly_window")))
        return SimulationConfig(initial_users=int(number("initial")), max_users=int(number("maximum")), duration_seconds=duration_seconds, requests_per_user=number("requests"), request_bytes=int(number("request_bytes")), response_bytes=int(number("response_bytes")), target_latency_ms=number("latency"), scenario=self.scenario.get(), detection_threshold=number("detect"), sudden_ramp_seconds=int(number("sudden_ramp")), intensity_base_rps=number("intensity"), normal_duration_seconds=int(number("normal")), detection_delay_seconds=int(number("detection_delay")), bandwidth_mbps=number("bandwidth"), real_time=True, mitigation=mitigation)

    def _apply_preset(self, _event=None):
        selected = preset(self.preset_name.get()).selected
        for name, variable in self.layer_vars.items():
            variable.set(name in selected)

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
        self.samples = []
        self.result = None
        self.running = True
        self.paused = False
        self.start_button.configure(state="disabled")
        self.pause_button.configure(state="normal", text="⏸ PAUSAR")
        config = self._config()
        self.active_config = config
        self.active_duration_unit = self.duration_unit.get()
        self.controls_panel.grid_remove()
        self.right_panel.grid(row=1, column=0, columnspan=2, sticky="nsew")
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

    def _run_worker(self):
        assert self.engine is not None
        result = self.engine.run(on_sample=lambda sample: self.after(0, self._on_sample, sample), on_event=lambda event: self.after(0, self._log, event))
        self.after(0, self._finished, result)

    def _on_sample(self, sample: SimulationSample):
        self.samples.append(sample)
        self._draw()
        config = self.active_config or self._config()
        duration = config.duration_seconds
        self.status.set(f"Exploración en ejecución · {config.scenario} · {self._duration_display(sample.second, duration)} · {sample.state}")
        self.progress_bar.configure(maximum=duration, value=sample.second)
        self._set_live_report(self._format_live_report(sample))

    def _finished(self, result: SimulationResult):
        self.result = result
        self.running = False
        self.paused = False
        config = self.active_config or self._config()
        self.start_button.configure(state="normal")
        self.pause_button.configure(state="disabled", text="⏸ PAUSAR")
        self.stop_button.configure(state="disabled")
        if len(result.samples) < config.duration_seconds:
            self.status.set(f"Exploración detenida · {self._duration_display(len(result.samples), config.duration_seconds)}")
        else:
            self.status.set(f"Exploración finalizada · {self._duration_display(len(result.samples), config.duration_seconds)} · Saturación máxima: {result.max_saturation:.1f}%")
        self.progress_bar.configure(maximum=max(1, config.duration_seconds), value=len(result.samples))
        self._set_live_report(
            "RESULTADO FINAL\n\n"
            f"Saturación máxima: {result.max_saturation:.1f}%\n"
            f"Tiempo en saturación: {result.time_saturated} s\n"
            f"Detección: {result.detected_at if result.detected_at is not None else 'No detectada'}\n"
            f"Mitigación: {result.mitigation_at if result.mitigation_at is not None else 'No activada'}\n"
            f"Recuperación: {result.recovery_at if result.recovery_at is not None else 'No alcanzada'}\n\n"
            "Capacidad estimada por el modelo; esta estimación es educativa y matemática y no representa una prueba de carga real.\n"
            "SIMULATED_COLLAPSE no significa que el servidor real haya caído."
        )
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
            ("Estado final", final_state),
        )
        cards = ttk.Frame(window)
        cards.grid(row=2, column=0, sticky="new", padx=18)
        for column in range(3):
            cards.columnconfigure(column, weight=1)
        for index, (label, value) in enumerate(kpis):
            card = ttk.LabelFrame(cards, text=label, padding=(12, 8))
            card.grid(row=index // 3, column=index % 3, sticky="ew", padx=5, pady=5)
            ttk.Label(card, text=value, style="Title.TLabel").pack(anchor="w")

        chart_frame = ttk.Frame(window)
        chart_frame.grid(row=3, column=0, sticky="nsew", padx=18, pady=(8, 12))
        window.rowconfigure(3, weight=1)
        figure = Figure(figsize=(11, 6), dpi=100, facecolor=PALETTE["panel"])
        axes = [figure.add_subplot(2, 2, index) for index in range(1, 5)]
        x = [sample.second for sample in samples]
        chart_specs = (
            ("Uso estimado de recursos", (("CPU", [s.cpu_percent for s in samples]), ("RAM", [s.ram_percent for s in samples])) , "%"),
            ("Saturación del servidor", (("Saturación", [s.saturation_percent for s in samples]),), "%"),
            ("Solicitudes por segundo", (("Generadas", [s.generated_requests_s for s in samples]), ("Procesadas", [s.processed_requests_s for s in samples])), "req/s"),
            ("Tráfico de red", (("Generado", [s.generated_traffic_mbps for s in samples]), ("Al origen", [s.traffic_to_origin_mbps for s in samples])), "Mbps"),
        )
        colors = (PALETTE["green"], PALETTE["amber"])
        for axis, (title, series, unit) in zip(axes, chart_specs):
            axis.set_facecolor(PALETTE["panel"])
            axis.set_title(title, color=PALETTE["green"], fontsize=10)
            axis.set_xlabel("Tiempo (s)", color=PALETTE["muted"])
            axis.set_ylabel(unit, color=PALETTE["muted"])
            axis.tick_params(colors=PALETTE["muted"], labelsize=8)
            axis.grid(alpha=0.2, color=PALETTE["muted"])
            for index, (name, values) in enumerate(series):
                axis.plot(x, values, label=name, color=colors[index], linewidth=1.8)
            if len(series) > 1:
                axis.legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8)
            for spine in axis.spines.values():
                spine.set_color("#315a48")
        axes[1].axhline(config.mitigation.anomaly_threshold, color=PALETTE["amber"], linestyle="--", linewidth=1, label="Umbral configurado")
        axes[1].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8)
        figure.tight_layout(pad=2.2)
        canvas = FigureCanvasTkAgg(figure, master=chart_frame)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        window.dashboard_canvas = canvas
        window.dashboard_figure = figure

        actions = ttk.Frame(window)
        actions.grid(row=4, column=0, sticky="e", padx=18, pady=(0, 16))
        ttk.Button(actions, text="Generar reporte TXT", command=self.save_report).pack(side="left", padx=5)
        ttk.Button(actions, text="Cerrar", command=window.destroy).pack(side="left", padx=5)

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
        if self.active_duration_unit == "Minutos":
            return f"{elapsed_seconds / 60:.1f}/{total_seconds / 60:g} min"
        return f"{int(elapsed_seconds)}/{int(total_seconds)} s"

    def stop(self):
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
        self.controls_panel.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 10))

    def reset(self):
        if self.running:
            self.reset_pending = True
            self.stop()
            self.status.set("Deteniendo antes de reiniciar…")
            return
        self.samples = []
        self.result = None
        self.progress_bar.configure(maximum=100, value=0)
        self._draw_empty()
        self.chart_widget.grid_remove()
        self._show_explorer()
        self.stop_button.configure(state="disabled")
        self._set_live_report("INFORME EN TIEMPO REAL\n\nLa simulación se reinició. No hay datos activos.")
        self.status.set("Sin simulación activa")

    @staticmethod
    def _format_live_report(sample: SimulationSample) -> str:
        return (
            "INFORME EN TIEMPO REAL | SIMULACIÓN LOCAL\n"
            f"Segundo: {sample.second} s\n"
            f"Estado: {sample.state} | Puntuación de anomalía: {sample.anomaly_score:.1f}/100\n\n"
            "CARGA DE USUARIOS\n"
            f"Generados: {sample.users_generated:,} | Legítimos estimados: {sample.users_legitimate:,} | "
            f"Sospechosos: {sample.users_suspicious:,} | Bloqueados: {sample.users_blocked:,}\n\n"
            "REQUESTS Y TRÁFICO\n"
            f"Generadas: {sample.requests_generated:,.1f} req/s\n"
            f"Procesadas por el modelo: {sample.processed_requests_s:,.1f} req/s\n"
            f"Limitadas: {sample.requests_limited:,.1f} | Bloqueadas: {sample.requests_blocked:,.1f} | "
            f"Challenge: {sample.requests_challenge:,.1f}\n"
            f"Tráfico generado: {sample.generated_traffic_mbps:,.2f} Mbps\n"
            f"Tráfico que llega al origen: {sample.traffic_to_origin_mbps:,.2f} Mbps\n\n"
            "RECURSOS ESTIMADOS DEL PERFIL\n"
            f"CPU: {sample.cpu_percent:.1f}% | RAM: {sample.ram_percent:.1f}% | "
            f"Saturación: {sample.saturation_percent:.1f}% | Latencia: {sample.latency_ms:.1f} ms\n"
            f"Capacidad modelada: {sample.capacity_rps:,.1f} req/s | Instancias: {sample.instances}\n\n"
            "Lectura: saturación es el mayor uso relativo estimado entre CPU, RAM y red."
        )

    def _set_live_report(self, value: str) -> None:
        self.live_report.configure(state="normal")
        self.live_report.delete("1.0", tk.END)
        self.live_report.insert("1.0", value)
        self.live_report.configure(state="disabled")

    def _draw_empty(self):
        titles = (
            "Tráfico generado y al origen (Mbps)",
            "Solicitudes generadas y procesadas (req/s)",
            "Uso de recursos y cuello de botella (%)",
            "Saturación y eventos del sistema (%)",
            "Carga virtual atendida (%)",
            "Solicitudes limitadas y bloqueadas (req/s)",
        )
        for index, (axis, title) in enumerate(zip(self.axes, titles)):
            axis.clear()
            axis.set_title(title, color=PALETTE["green"], fontsize=9, pad=9)
            axis.tick_params(colors=PALETTE["muted"], labelsize=8)
            axis.set_facecolor(PALETTE["panel"])
            axis.set_xlabel("Tiempo (s)", color=PALETTE["muted"], fontsize=8)
            if index in {2, 3, 4}:
                axis.set_ylim(0, 100)
                axis.set_ylabel("Porcentaje", color=PALETTE["muted"], fontsize=8)
            if not self.samples:
                axis.text(0.5, 0.5, "Inicia una exploración para ver datos", transform=axis.transAxes, ha="center", va="center", color=PALETTE["muted"], fontsize=8)
            for spine in axis.spines.values():
                spine.set_color("#315a48")
        self.canvas.draw_idle()

    def _draw(self):
        if not self.samples:
            return
        self._draw_empty()
        x = [sample.second for sample in self.samples]
        config = self.active_config or self._config()
        network_capacity = CapacityModel(self.profile, config).network_capacity_mbps if self.profile else 10.0
        network_usage = [
            min(
                100.0,
                sample.traffic_to_origin_mbps
                / max(network_capacity * max(sample.instances, 1) * max(len(sample.server_loads), 1), 0.001)
                * 100.0,
            )
            for sample in self.samples
        ]
        served_share = [
            min(100.0, (sample.processed_requests_s + sample.requests_cache) / sample.requests_generated * 100.0)
            if sample.requests_generated > 0 else 0.0
            for sample in self.samples
        ]
        values = (
            (("Generado", [sample.generated_traffic_mbps for sample in self.samples]), ("Al origen", [sample.traffic_to_origin_mbps for sample in self.samples])),
            (("Generadas", [sample.generated_requests_s for sample in self.samples]), ("Procesadas", [sample.processed_requests_s for sample in self.samples])),
            (("CPU", [sample.cpu_percent for sample in self.samples]), ("RAM", [sample.ram_percent for sample in self.samples]), ("Red", network_usage)),
            (("Saturación", [sample.saturation_percent for sample in self.samples]),),
            (("Atendida", served_share),),
            (("Limitadas", [sample.requests_limited for sample in self.samples]), ("Bloqueadas", [sample.requests_blocked for sample in self.samples])),
        )
        colors = (PALETTE["green"], PALETTE["amber"], "#63b3ed")
        for axis, series in zip(self.axes, values):
            for index, (label, data) in enumerate(series):
                axis.plot(x, data, label=label, color=colors[index], linewidth=1.8)
            if len(series) > 1:
                axis.legend(frameon=False, labelcolor=PALETTE["text"], fontsize=7, ncol=min(3, len(series)))
            axis.grid(alpha=0.18, color=PALETTE["muted"])

        current = self.samples[-1]
        bottleneck, bottleneck_usage = max(
            (("CPU", current.cpu_percent), ("RAM", current.ram_percent), ("Red", network_usage[-1])),
            key=lambda item: item[1],
        )
        self.axes[2].text(
            0.98, 0.96, f"Cuello: {bottleneck} ({bottleneck_usage:.0f}%)",
            transform=self.axes[2].transAxes, ha="right", va="top", fontsize=8,
            color=PALETTE["text"],
            bbox={"boxstyle": "round,pad=0.3", "facecolor": PALETTE["panel2"], "edgecolor": "#315a48", "alpha": 0.9},
        )

        saturation_axis = self.axes[3]
        saturation_axis.axhline(config.high_load_threshold, color=PALETTE["amber"], linestyle="--", linewidth=1, label=f"Carga alta ({config.high_load_threshold:g}%)")
        saturation_axis.axhline(config.saturated_threshold, color=PALETTE["danger"], linestyle="--", linewidth=1, label=f"Saturación ({config.saturated_threshold:g}%)")
        if self.result:
            detected_at = self.result.detected_at
            mitigation_at = self.result.mitigation_at
            recovery_at = self.result.recovery_at
        else:
            detected_at = next((sample.second for sample in self.samples if "DETECTADA" in sample.state or sample.state.startswith("MITIGACI") or sample.state == "RECUPERADO"), None)
            mitigation_at = next((sample.second for sample in self.samples if sample.state.startswith("MITIGACI") or sample.state == "RECUPERADO"), None)
            recovery_at = next((sample.second for sample in self.samples if sample.state == "RECUPERADO"), None)
        events = (
            (detected_at, "Detección", "#63b3ed"),
            (mitigation_at, "Mitigación", "#b794f4"),
            (recovery_at, "Recuperación", "#f6e58d"),
        )
        for second, label, color in events:
            if second is not None:
                saturation_axis.axvline(second, color=color, linestyle=":", linewidth=1.4, label=f"{label} \u00b7 {second}s")
        saturation_axis.legend(frameon=False, labelcolor=PALETTE["text"], fontsize=6.5, ncol=2, loc="upper left")
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
