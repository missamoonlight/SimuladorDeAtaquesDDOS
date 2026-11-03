from __future__ import annotations

import csv
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from aplicacion.interfaz.componentes_interfaz import PALETTE
from aplicacion.modelos.perfil_servidor import ServerProfile
from aplicacion.modelos.configuracion_simulacion import MITIGATION_NAMES, MitigationConfig, SimulationConfig, preset
from aplicacion.ejecutor_experimental import run_factorial
from aplicacion.reportes.generador_reportes import export_csv, generate_report
from aplicacion.simulacion.modelo_capacidad import CapacityModel
from aplicacion.simulacion.motor_simulacion import SimulationEngine, SimulationResult, SimulationSample, compare_mitigations


class SimulatorView(ttk.Frame):
    def __init__(self, parent, on_back):
        super().__init__(parent)
        self.profile: ServerProfile | None = None
        self.engine: SimulationEngine | None = None
        self.result: SimulationResult | None = None
        self.running = False
        self.samples: list[SimulationSample] = []
        self.vars = {name: tk.StringVar(value=value) for name, value in {
            "initial": "20", "maximum": "1000", "duration": "60", "requests": "1.0", "request_bytes": "2048", "response_bytes": "16384", "latency": "200", "detect": "70", "sudden_ramp": "5", "intensity": "10000", "normal": "30", "detection_delay": "15", "bandwidth": "0", "rate_limit": "500", "cache_hit": "80", "edge_filter": "90", "anomaly_window": "3",
        }.items()}
        self.scenario = tk.StringVar(value="Gradual")
        self.preset_name = tk.StringVar(value="Protección básica")
        self.layer_vars = {name: tk.BooleanVar(value=name == "Rate Limiting") for name in MITIGATION_NAMES}
        self.status = tk.StringVar(value="Sin simulación activa")
        self._build(on_back)

    def _build(self, on_back):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text="SIMULADOR DE RESILIENCIA", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(12, 8))
        # Acciones de entrega: piloto para calibración y lote factorial formal.
        experiment_actions = ttk.Frame(self)
        experiment_actions.grid(row=0, column=1, sticky="e", pady=(12, 8))
        self.experiment_button = ttk.Button(experiment_actions, text="LOTE FORMAL ×30", command=self.run_protocol_experiment)
        self.experiment_button.pack(side="right", padx=(6, 0))
        self.pilot_button = ttk.Button(experiment_actions, text="PILOTAJE ×10", command=self.run_protocol_pilot)
        self.pilot_button.pack(side="right")
        controls = ttk.LabelFrame(self, text="EXPLORADOR INTERACTIVO (NO FACTORIAL)", padding=10)
        controls.grid(row=1, column=0, sticky="nsw", padx=(0, 10))
        fields = [("Usuarios iniciales", "initial"), ("Usuarios máximos", "maximum"), ("Duración (s)", "duration"), ("Intensidad base (req/s)", "intensity"), ("Inicio ataque (s)", "normal"), ("Tiempo detección (s)", "detection_delay"), ("Ancho banda Mbps (0=perfil)", "bandwidth"), ("Requests / usuario / s", "requests"), ("Bytes / request", "request_bytes"), ("Bytes / response", "response_bytes"), ("Latencia objetivo (ms)", "latency"), ("Umbral anomalía %", "detect"), ("Rampa repentina (s)", "sudden_ramp")]
        for row, (label, key) in enumerate(fields):
            ttk.Label(controls, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(controls, textvariable=self.vars[key], width=12).grid(row=row, column=1, pady=3)
        ttk.Label(controls, text="Escenario").grid(row=13, column=0, sticky="w", pady=3)
        ttk.Combobox(controls, textvariable=self.scenario, values=("Gradual", "Repentino", "Pulsante", "Spike", "Personalizado"), state="readonly", width=11).grid(row=13, column=1, pady=3)
        ttk.Label(controls, text="CAPAS DE MITIGACIÓN", foreground=PALETTE["green"]).grid(row=14, column=0, columnspan=2, sticky="w", pady=(12, 3))
        layers = ttk.Frame(controls)
        layers.grid(row=15, column=0, columnspan=2, sticky="w")
        for index, name in enumerate(MITIGATION_NAMES):
            tk.Checkbutton(layers, text=name, variable=self.layer_vars[name], bg=PALETTE["panel"], fg=PALETTE["text"], activebackground=PALETTE["panel"], activeforeground=PALETTE["green"], selectcolor="#1d4d38", anchor="w").grid(row=index // 2, column=index % 2, sticky="w")
        ttk.Label(controls, text="Preset").grid(row=21, column=0, sticky="w", pady=(8, 2))
        ttk.Combobox(controls, textvariable=self.preset_name, values=("Protección básica", "Protección web", "Protección avanzada", "Alta disponibilidad", "Defensa multicapa"), state="readonly", width=16).grid(row=21, column=1, sticky="ew")
        ttk.Button(controls, text="Aplicar preset", command=self._apply_preset).grid(row=22, column=0, columnspan=2, sticky="ew", pady=2)
        for row, (label, key) in enumerate((("Límite req/s", "rate_limit"), ("Cache hit %", "cache_hit"), ("Edge filtrado %", "edge_filter"), ("Ventana anomalía", "anomaly_window")), 23):
            ttk.Label(controls, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(controls, textvariable=self.vars[key], width=12).grid(row=row, column=1, pady=2)
        self.start_button = ttk.Button(controls, text="▶ INICIAR EXPLORACIÓN", command=self.start)
        self.start_button.grid(row=27, column=0, columnspan=2, sticky="ew", pady=(14, 4))
        self.pause_button = ttk.Button(controls, text="⏸ PAUSAR", command=self.pause, state="disabled")
        self.pause_button.grid(row=28, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(controls, text="⏹ DETENER", command=self.stop).grid(row=29, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(controls, text="↻ REINICIAR", command=self.reset).grid(row=30, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(controls, text="📊 REPORTE", command=self.save_report).grid(row=31, column=0, columnspan=2, sticky="ew", pady=(10, 2))
        ttk.Button(controls, text="💾 EXPORTAR CSV", command=self.save_csv).grid(row=32, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(controls, text="COMPARAR MITIGACIONES", command=self.compare).grid(row=33, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(controls, text="¿CÓMO FUNCIONA?", command=self.show_help).grid(row=34, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(controls, text="VOLVER AL PERFIL", command=on_back).grid(row=35, column=0, columnspan=2, sticky="ew", pady=(14, 2))
        ttk.Label(controls, textvariable=self.status, wraplength=190).grid(row=36, column=0, columnspan=2, sticky="w", pady=(12, 0))

        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=0)
        right.rowconfigure(2, weight=0)
        self.figure = Figure(figsize=(10, 11), dpi=100, facecolor=PALETTE["panel"])
        self.axes = [self.figure.add_subplot(5, 2, index) for index in range(1, 11)]
        self.figure.tight_layout(pad=2.5)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.live_report = tk.Text(right, height=8, state="disabled", bg="#0f1916", fg=PALETTE["text"], relief="flat", font=("Consolas", 9), wrap="word")
        self.live_report.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.event_log = tk.Text(right, height=5, state="disabled", bg="#0f1916", fg="#89a79a", relief="flat", font=("Consolas", 9))
        self.event_log.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self._set_live_report("EXPLORACIÓN INTERACTIVA\n\nUsa el botón superior para ejecutar el diseño factorial del protocolo.\n\nCapacidad estimada por el modelo; esta estimación es educativa y matemática y no representa una prueba de carga real.")
        self._draw_empty()

    def set_profile(self, profile: ServerProfile):
        self.profile = profile
        estimate = CapacityModel(profile, self._config()).summary() if self._valid_config(show_error=False) else "Perfil listo. Configura la simulación."
        self._log(estimate)

    def _config(self) -> SimulationConfig:
        number = lambda key: float(self.vars[key].get())
        selected = tuple(name for name, variable in self.layer_vars.items() if variable.get())
        mitigation = MitigationConfig(selected=selected, rate_limit_rps=number("rate_limit"), cdn_hit_ratio=number("cache_hit"), edge_filter_percent=number("edge_filter"), anomaly_window_seconds=int(number("anomaly_window")))
        return SimulationConfig(initial_users=int(number("initial")), max_users=int(number("maximum")), duration_seconds=int(number("duration")), requests_per_user=number("requests"), request_bytes=int(number("request_bytes")), response_bytes=int(number("response_bytes")), target_latency_ms=number("latency"), scenario=self.scenario.get(), detection_threshold=number("detect"), sudden_ramp_seconds=int(number("sudden_ramp")), intensity_base_rps=number("intensity"), normal_duration_seconds=int(number("normal")), detection_delay_seconds=int(number("detection_delay")), bandwidth_mbps=number("bandwidth"), mitigation=mitigation)

    def _apply_preset(self):
        selected = preset(self.preset_name.get()).selected
        for name, variable in self.layer_vars.items():
            variable.set(name in selected)

    def show_help(self):
        descriptions = {
            "Rate Limiting": "Corta las requests procesadas al límite req/s; las excedentes quedan limitadas.",
            "Rate-Based Ban": "Acumula evaluaciones sobre el umbral y bloquea fuentes abstractas durante un tiempo.",
            "Blacklisting": "Identifica y bloquea usuarios sospechosos sin reducir directamente los legítimos.",
            "CAPTCHA / Challenge": "Envía clientes sospechosos a challenge; solo una probabilidad configurable lo supera.",
            "WAF / Filtrado L7": "Filtra tráfico sospechoso antes del origen e incorpora falsos positivos, CPU y latencia.",
            "Bot Management": "Clasifica comportamiento abstracto y bloquea o desafía bots simulados.",
            "Auto Scaling": "Aumenta instancias por intervalos cuando la carga excede la capacidad modelada.",
            "CDN / Caching": "Atiende el porcentaje cacheado sin enviarlo al origen.",
            "Load Balancing": "Distribuye matemáticamente la capacidad entre servidores modelados.",
            "Edge / Scrubbing": "Filtra tráfico antes del origen según capacidad y porcentaje configurados.",
        }
        selected = [name for name, variable in self.layer_vars.items() if variable.get()]
        messagebox.showinfo("Mitigaciones seleccionadas", "\n\n".join(f"{name}: {descriptions[name]}" for name in selected) or "No hay capas seleccionadas.")

    def compare(self):
        if not self.profile or not self._valid_config():
            return
        self.status.set("Comparando capas localmente...")
        config = self._config()
        threading.Thread(target=self._compare_worker, args=(config,), daemon=True).start()

    def run_protocol_experiment(self):
        self._launch_protocol_experiment(30)

    def run_protocol_pilot(self):
        self._launch_protocol_experiment(10)

    def _launch_protocol_experiment(self, repetitions):
        if not self.profile:
            messagebox.showinfo("Sin perfil", "Carga o importa un ServerProfile antes del experimento.")
            return
        if self.running:
            messagebox.showinfo("Simulación activa", "Detén la simulación interactiva antes de iniciar el lote.")
            return
        self.experiment_button.configure(state="disabled")
        self.pilot_button.configure(state="disabled")
        self.status.set(f"Preparando {402 * repetitions:,} ejecuciones locales del protocolo...")
        threading.Thread(target=self._experiment_worker, args=(self.profile, repetitions), daemon=True).start()

    def _experiment_worker(self, profile, repetitions):
        output = Path(__file__).resolve().parents[2] / "datos" / "reportes"
        try:
            summary, trace = run_factorial(profile, output, repetitions=repetitions,
                progress=lambda done, total: self.after(0, self.status.set, f"Experimento: {done:,}/{total:,} ejecuciones"))
        except Exception as error:
            self.after(0, self._experiment_failed, str(error))
            return
        self.after(0, self._experiment_finished, summary, trace, repetitions)

    def _experiment_failed(self, error):
        self.experiment_button.configure(state="normal")
        self.pilot_button.configure(state="normal")
        self.status.set("Experimento no completado")
        messagebox.showerror("Error en el experimento", error)

    def _experiment_finished(self, summary, trace, repetitions):
        self.experiment_button.configure(state="normal")
        self.pilot_button.configure(state="normal")
        self.status.set("Experimento factorial finalizado")
        self._show_experiment_dashboard(summary, trace, repetitions)

    def _show_experiment_dashboard(self, summary_path, trace_path, repetitions):
        with Path(summary_path).open("r", newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            messagebox.showwarning("Sin resultados", "El experimento terminó, pero el resumen no contiene filas.")
            return

        window = tk.Toplevel(self)
        window.title("Dashboard del experimento factorial")
        window.geometry("1120x780")
        window.minsize(900, 620)
        window.configure(bg=PALETTE["panel"])
        window.columnconfigure(0, weight=1)
        window.rowconfigure(3, weight=1)
        ttk.Label(window, text="DASHBOARD DEL EXPERIMENTO", style="Title.TLabel").grid(
            row=0, column=0, sticky="w", padx=18, pady=(16, 4)
        )
        ttk.Label(
            window,
            text=f"{len(rows):,} ejecuciones | {repetitions} repeticiones por condición. Resultados estimados por el modelo local.",
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 12))

        numeric = lambda row, key: float(row[key]) if row.get(key) else 0.0
        attacks = [row for row in rows if row.get("scenario") != "Control"]
        avg_saturation = sum(numeric(row, "max_saturation_percent") for row in attacks) / max(1, len(attacks))
        detected = [row for row in attacks if row.get("detection_time_s")]
        recoveries = [row for row in attacks if row.get("recovery_censored", "").lower() != "true"]
        avg_served = sum(numeric(row, "served_proportion") for row in attacks) / max(1, len(attacks)) * 100
        cards = ttk.Frame(window)
        cards.grid(row=2, column=0, sticky="new", padx=18)
        for column in range(4):
            cards.columnconfigure(column, weight=1)
        kpis = (
            ("Ejecuciones", f"{len(rows):,}"),
            ("Saturación máxima media", f"{avg_saturation:.1f}%"),
            ("Detección registrada", f"{len(detected) / max(1, len(attacks)) * 100:.1f}%"),
            ("Demanda atendida media", f"{avg_served:.1f}%"),
        )
        for index, (label, value) in enumerate(kpis):
            card = ttk.LabelFrame(cards, text=label, padding=(10, 8))
            card.grid(row=0, column=index, sticky="ew", padx=5, pady=5)
            ttk.Label(card, text=value, style="Title.TLabel").pack(anchor="w")

        figure = Figure(figsize=(10.5, 5.5), dpi=100, facecolor=PALETTE["panel"])
        axes = [figure.add_subplot(2, 2, index) for index in range(1, 5)]
        user_levels = sorted({int(row["peak_users"]) for row in attacks})
        profiles = sorted({row["profile_id"] for row in attacks})
        for profile_id, color in zip(profiles, (PALETTE["green"], PALETTE["amber"])):
            means = []
            for users in user_levels:
                group = [row for row in attacks if row["profile_id"] == profile_id and int(row["peak_users"]) == users]
                means.append(sum(numeric(row, "max_saturation_percent") for row in group) / max(1, len(group)))
            axes[0].plot(user_levels, means, marker="o", label=profile_id, color=color)
        axes[0].set_title("Saturación media por usuarios")
        axes[0].set_xlabel("Usuarios maliciosos máximos")
        axes[0].set_ylabel("Saturación (%)")
        axes[0].legend(frameon=False, labelcolor=PALETTE["text"])

        scenarios = sorted({row["scenario"] for row in attacks})
        scenario_means = [
            sum(numeric(row, "max_saturation_percent") for row in attacks if row["scenario"] == scenario)
            / max(1, sum(row["scenario"] == scenario for row in attacks))
            for scenario in scenarios
        ]
        axes[1].bar(scenarios, scenario_means, color=PALETTE["green"])
        axes[1].set_title("Saturación media por escenario")
        axes[1].set_ylabel("Saturación (%)")
        axes[1].tick_params(axis="x", rotation=20)

        strategies = sorted({row["strategy"] for row in attacks})
        served_means = [
            sum(numeric(row, "served_proportion") for row in attacks if row["strategy"] == strategy)
            / max(1, sum(row["strategy"] == strategy for row in attacks)) * 100
            for strategy in strategies
        ]
        axes[2].bar(strategies, served_means, color=PALETTE["amber"])
        axes[2].set_title("Demanda atendida por estrategia")
        axes[2].set_ylabel("Porcentaje (%)")
        axes[2].tick_params(axis="x", rotation=25, labelsize=8)

        recovery_means = [
            sum(numeric(row, "recovery_time_s") for row in recoveries if row["strategy"] == strategy)
            / max(1, sum(row["strategy"] == strategy for row in recoveries))
            for strategy in strategies
        ]
        axes[3].bar(strategies, recovery_means, color=PALETTE["green"])
        axes[3].set_title("Recuperación media observada")
        axes[3].set_ylabel("Segundos desde el ataque")
        axes[3].tick_params(axis="x", rotation=25, labelsize=8)
        for axis in axes:
            axis.set_facecolor(PALETTE["panel"])
            axis.grid(axis="y", alpha=0.2, color=PALETTE["muted"])
            axis.tick_params(colors=PALETTE["muted"], labelsize=8)
            axis.title.set_color(PALETTE["green"])
            axis.xaxis.label.set_color(PALETTE["muted"])
            axis.yaxis.label.set_color(PALETTE["muted"])
            for spine in axis.spines.values():
                spine.set_color("#315a48")
        figure.tight_layout(pad=2.2)
        canvas = FigureCanvasTkAgg(figure, master=window)
        canvas.get_tk_widget().grid(row=3, column=0, sticky="nsew", padx=18, pady=10)
        window.dashboard_canvas = canvas
        window.dashboard_figure = figure

        files = ttk.Frame(window)
        files.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 14))
        ttk.Label(files, text=f"Resumen: {summary_path}\nBitácora comprimida: {trace_path}", wraplength=880).pack(side="left", anchor="w")
        ttk.Button(files, text="Cerrar", command=window.destroy).pack(side="right")

    def _compare_worker(self, config):
        rows = compare_mitigations(self.profile, config)
        self.after(0, self._show_comparison, rows)

    def _show_comparison(self, rows):
        window = tk.Toplevel(self)
        window.title("Comparación de mitigaciones")
        window.geometry("900x420")
        tree = ttk.Treeview(window, columns=("name", "sat", "cpu", "ram", "lat", "blocked", "recovery"), show="headings")
        headings = {"name": "Mitigación", "sat": "Max saturación %", "cpu": "CPU max %", "ram": "RAM max %", "lat": "Latencia max ms", "blocked": "Requests bloqueadas", "recovery": "Recuperación"}
        for key, label in headings.items():
            tree.heading(key, text=label)
            tree.column(key, width=125 if key != "name" else 180)
        for row in rows:
            tree.insert("", "end", values=(row.name, f"{row.max_saturation:.1f}", f"{row.max_cpu:.1f}", f"{row.max_ram:.1f}", f"{row.max_latency:.1f}", f"{row.requests_blocked:.1f}", row.recovery_time or "N/D"))
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.status.set("Comparación terminada")

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
        self.start_button.configure(state="disabled")
        self.pause_button.configure(state="normal", text="⏸ PAUSAR")
        self.status.set("Simulación local en ejecución")
        config = self._config()
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
        self.status.set(f"Segundo {sample.second} de {self._config().duration_seconds} | Estado: {sample.state}")
        self._set_live_report(self._format_live_report(sample))

    def _finished(self, result: SimulationResult):
        self.result = result
        self.running = False
        self.start_button.configure(state="normal")
        self.pause_button.configure(state="disabled", text="⏸ PAUSAR")
        self.status.set(f"Simulación finalizada | Saturación máxima: {result.max_saturation:.1f}%")
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
        self._log("Simulación finalizada. Consulta el informe en tiempo real, el reporte TXT o el CSV.")
        if result.samples:
            self._show_results_dashboard()

    def _show_results_dashboard(self):
        """Abre un tablero final con indicadores y series de la simulación."""
        if not self.result or not self.result.samples:
            return

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
            text="Indicadores calculados por el modelo local; representan estimaciones, no mediciones del servidor real.",
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
        axes[1].axhline(float(self.vars["detect"].get()), color=PALETTE["amber"], linestyle="--", linewidth=1, label="Umbral configurado")
        axes[1].legend(frameon=False, labelcolor=PALETTE["text"], fontsize=8)
        figure.tight_layout(pad=2.2)
        canvas = FigureCanvasTkAgg(figure, master=chart_frame)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        window.dashboard_canvas = canvas
        window.dashboard_figure = figure

        actions = ttk.Frame(window)
        actions.grid(row=4, column=0, sticky="e", padx=18, pady=(0, 16))
        ttk.Button(actions, text="Exportar CSV", command=self.save_csv).pack(side="left", padx=5)
        ttk.Button(actions, text="Generar reporte TXT", command=self.save_report).pack(side="left", padx=5)
        ttk.Button(actions, text="Cerrar", command=window.destroy).pack(side="left", padx=5)

    def pause(self):
        if not self.engine:
            return
        if self.pause_button.cget("text").startswith("⏸"):
            self.engine.pause()
            self.pause_button.configure(text="▶ CONTINUAR")
            self.status.set("Simulación pausada")
        else:
            self.engine.resume()
            self.pause_button.configure(text="⏸ PAUSAR")
            self.status.set("Simulación local en ejecución")

    def stop(self):
        if self.engine:
            self.engine.stop()
        self.status.set("Deteniendo simulación...")

    def reset(self):
        self.stop()
        self.samples = []
        self.result = None
        self._draw_empty()
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
        titles = ("Tráfico generado / origen Mbps", "Requests generadas / procesadas", "CPU estimada %", "RAM estimada %", "Saturación %", "Latencia ms", "Usuarios legítimos preservados", "Requests bloqueadas", "Capacidad req/s", "Instancias")
        for axis, title in zip(self.axes, titles):
            axis.clear()
            axis.set_title(title, color=PALETTE["green"], fontsize=9)
            axis.tick_params(colors=PALETTE["muted"], labelsize=8)
            axis.set_facecolor(PALETTE["panel"])
            for spine in axis.spines.values():
                spine.set_color("#315a48")
        self.canvas.draw_idle()

    def _draw(self):
        if not self.samples:
            return
        self._draw_empty()
        x = [item.second for item in self.samples]
        values = [
            ([item.generated_traffic_mbps for item in self.samples], [item.traffic_to_origin_mbps for item in self.samples]),
            ([item.generated_requests_s for item in self.samples], [item.processed_requests_s for item in self.samples]),
            ([item.cpu_percent for item in self.samples],),
            ([item.ram_percent for item in self.samples],),
            ([item.saturation_percent for item in self.samples],),
            ([item.latency_ms for item in self.samples],),
            ([item.legitimate_preserved for item in self.samples],),
            ([item.requests_blocked for item in self.samples],),
            ([item.capacity_rps for item in self.samples],),
            ([item.instances for item in self.samples],),
        ]
        for axis, series in zip(self.axes, values):
            for index, data in enumerate(series):
                axis.plot(x, data, color=PALETTE["green"] if index == 0 else PALETTE["amber"], linewidth=2)
            axis.grid(alpha=0.15, color=PALETTE["muted"])
        self.axes[3].axhline(float(self.vars["detect"].get()), color=PALETTE["amber"], linestyle="--", linewidth=1)
        self.figure.tight_layout(pad=2.5)
        self.canvas.draw_idle()

    def _log(self, text: str):
        self.event_log.configure(state="normal")
        self.event_log.insert("end", f"[{__import__('datetime').datetime.now():%H:%M:%S}] {text}\n")
        self.event_log.see("end")
        self.event_log.configure(state="disabled")

    def save_csv(self):
        if not self.result or not self.result.samples:
            messagebox.showinfo("Sin resultados", "Ejecuta una simulación antes de exportar.")
            return
        path = export_csv(self.result, Path("datos/reportes"))
        messagebox.showinfo("CSV exportado", str(path))

    def save_report(self):
        if not self.result or not self.profile:
            messagebox.showinfo("Sin resultados", "Ejecuta una simulación antes de generar el reporte.")
            return
        config = self._config()
        path = generate_report(self.profile, config, self.result, CapacityModel(self.profile, config), Path("datos/reportes"))
        messagebox.showinfo("Reporte generado", str(path))
