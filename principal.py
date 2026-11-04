from __future__ import annotations

import json
import logging
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from aplicacion.interfaz.vista_inicio_sesion import LoginView
from aplicacion.interfaz.vista_perfil import ProfileView
from aplicacion.interfaz.vista_simulador import SimulatorView
from aplicacion.interfaz.componentes_interfaz import configure_style
from aplicacion.modelos.perfil_servidor import ServerProfile, demo_profile
from aplicacion.perfilador.perfilador_servidor import ServerProfiler
from aplicacion.conexion_ssh.gestor_ssh import SSHConnectionError, SSHManager


ROOT = Path(__file__).resolve().parent
(ROOT / "datos" / "perfiles").mkdir(parents=True, exist_ok=True)
(ROOT / "datos" / "reportes").mkdir(parents=True, exist_ok=True)
(ROOT / "registros").mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=ROOT / "registros" / "app.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class ResilienceApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Simulador de resiliencia")
        self.root.geometry("1180x800")
        self.root.minsize(980, 680)
        configure_style(root)
        self.profile: ServerProfile | None = None
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(10, 16))

        self.connection_profile = ttk.Frame(self.notebook)
        self.connection_profile.columnconfigure(0, weight=1, uniform="panels")
        self.connection_profile.columnconfigure(1, weight=0)
        self.connection_profile.columnconfigure(2, weight=1, uniform="panels")
        self.connection_profile.rowconfigure(0, weight=1)
        self.login = LoginView(self.connection_profile, self.collect_profile, self.load_demo, self.import_profile, self.save_current_profile)
        self.profile_view = ProfileView(self.connection_profile, self.open_simulator, self.open_login)
        self.login.grid(row=0, column=0, sticky="nsew", padx=(8, 5), pady=8)
        ttk.Separator(self.connection_profile, orient="vertical").grid(row=0, column=1, sticky="nsw")
        self.profile_view.grid(row=0, column=2, sticky="nsew", padx=(8, 5), pady=8)
        self.simulator = SimulatorView(self.notebook, self.open_profile)
        self.notebook.add(self.connection_profile, text="  CONEXIÓN Y PERFIL  ")
        self.notebook.add(self.simulator, text="  SIMULACIÓN  ")
        self.notebook.tab(self.simulator, state="disabled")
        self.notebook.select(0)

    def collect_profile(self) -> None:
        values = self.login.values()
        try:
            port = int(values["port"])
            if not values["host"] or not values["username"] or not 1 <= port <= 65535:
                raise ValueError("Indica host, usuario y un puerto entre 1 y 65535.")
            if values["auth"] == "Contraseña" and not values["password"]:
                raise ValueError("Escribe la contraseña o selecciona autenticación por clave SSH.")
            if values["auth"] == "Clave SSH" and not values["key_file"]:
                raise ValueError("Selecciona un archivo de clave SSH.")
        except ValueError as error:
            messagebox.showerror("Datos inválidos", str(error))
            return
        self.login.busy(True)
        self.login.set_status("Conectando con SSH de solo lectura...")
        threading.Thread(target=self._collect_worker, args=(values, port), daemon=True).start()

    def _collect_worker(self, values: dict[str, str], port: int) -> None:
        try:
            password = values["password"] if values["auth"] == "Contraseña" else ""
            key_file = values["key_file"] if values["auth"] == "Clave SSH" else ""
            manager = SSHManager(values["host"], port, values["username"], password, key_file)
            raw = manager.collect()
            profile = ServerProfiler().build_profile(raw, source=f"SSH: {values['host']}")
        except (SSHConnectionError, OSError, ValueError) as error:
            logging.error("SSH/profile collection failed: %s", error)
            self.root.after(0, self._collection_failed, str(error))
            return
        self.root.after(0, self._collection_succeeded, profile)

    def _collection_succeeded(self, profile: ServerProfile) -> None:
        self.login.password.set("")
        self.login.busy(False)
        self.set_profile(profile)
        self.login.set_status("Perfil obtenido correctamente. Contraseña descartada.")
        self.open_profile()

    def _collection_failed(self, error: str) -> None:
        self.login.busy(False)
        self.login.set_status("No se pudo obtener el perfil")
        messagebox.showerror("Error SSH", error)

    def load_demo(self) -> None:
        self.set_profile(demo_profile())
        self.login.set_status("PERFIL DEMOSTRACIÓN cargado; no se abrió ninguna conexión.")
        self.open_profile()

    def import_profile(self) -> None:
        path = filedialog.askopenfilename(title="Cargar perfil JSON", filetypes=[("Perfil JSON", "*.json")])
        if not path:
            return
        try:
            profile = ServerProfile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            messagebox.showerror("Perfil inválido", f"No se pudo cargar el perfil:\n{error}")
            return
        self.set_profile(profile)
        self.login.set_status("Perfil JSON cargado sin conexión SSH.")
        self.open_profile()

    def set_profile(self, profile: ServerProfile) -> None:
        self.profile = profile
        self.profile_view.set_profile(profile)
        self.simulator.set_profile(profile)
        self.notebook.tab(self.simulator, state="normal")

    def save_current_profile(self) -> None:
        if self.profile:
            self.profile_view.save()
        else:
            messagebox.showinfo("Sin perfil", "Obtén o carga un perfil antes de guardarlo.")

    def open_login(self) -> None:
        self.notebook.select(0)

    def open_profile(self) -> None:
        self.notebook.select(0)

    def open_simulator(self) -> None:
        if not self.profile:
            messagebox.showinfo("Sin perfil", "Carga un perfil antes de simular.")
            return
        self.notebook.select(self.simulator)


def main() -> None:
    root = tk.Tk()
    ResilienceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
