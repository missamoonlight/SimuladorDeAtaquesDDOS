from __future__ import annotations

import csv
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from app.gui.widgets import PALETTE
from app.models.server_profile import ServerProfile
from app.models.simulation_config import MITIGATION_NAMES, MitigationConfig, SimulationConfig, preset
from app.experiment_runner import run_factorial
from app.reports.report_generator import export_csv, generate_report
from app.simulation.capacity_model import CapacityModel
from app.simulation.simulation_engine import SimulationEngine, SimulationResult, SimulationSample, compare_mitigations


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
        output = Path(__file__).resolve().parents[2] / "data" / "reports"
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
        messagebox.showinfo("Experimento completado", f"Resumen ({402 * repetitions:,} ejecuciones):\n{summary}\n\nBitácora CSV por segundo (comprimida):\n{trace}")

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
        path = export_csv(self.result, Path("data/reports"))
        messagebox.showinfo("CSV exportado", str(path))

    def save_report(self):
        if not self.result or not self.profile:
            messagebox.showinfo("Sin resultados", "Ejecuta una simulación antes de generar el reporte.")
            return
        config = self._config()
        path = generate_report(self.profile, config, self.result, CapacityModel(self.profile, config), Path("data/reports"))
        messagebox.showinfo("Reporte generado", str(path))
