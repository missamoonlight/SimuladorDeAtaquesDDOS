from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.gui.widgets import PALETTE, labeled_entry


class LoginView(ttk.Frame):
    def __init__(self, parent, on_collect, on_demo, on_import, on_save_profile):
        super().__init__(parent)
        self.on_collect = on_collect
        self.on_demo = on_demo
        self.on_import = on_import
        self.on_save_profile = on_save_profile
        self.host = tk.StringVar()
        self.port = tk.StringVar(value="22")
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.key_file = tk.StringVar()
        self.auth = tk.StringVar(value="Contraseña")
        self.status = tk.StringVar(value="Listo. La simulación nunca genera tráfico remoto.")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="SIMULADOR DE RESILIENCIA Y CAPACIDAD DE SERVIDORES", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(12, 2))
        ttk.Label(self, text="Evaluación segura mediante perfilado SSH y simulación local", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 14))
        warning = tk.Label(self, text="⚠ MODO SEGURO\nEl servidor solo se consulta mediante comandos de diagnóstico de lectura.\nLa simulación NO genera tráfico hacia el servidor.", bg="#2c2413", fg=PALETTE["amber"], justify="left", anchor="w", padx=14, pady=10)
        warning.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        frame = ttk.LabelFrame(self, text="CONEXIÓN SSH", padding=14)
        frame.grid(row=3, column=0, sticky="new")
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        labeled_entry(frame, "Host / Dirección IP", self.host, 0, 0)
        labeled_entry(frame, "Puerto SSH", self.port, 0, 2, width=8)
        labeled_entry(frame, "Usuario", self.username, 1, 0)
        ttk.Label(frame, text="Método de autenticación").grid(row=1, column=2, sticky="w", padx=6, pady=5)
        auth = ttk.Combobox(frame, textvariable=self.auth, values=("Contraseña", "Clave SSH"), state="readonly", width=17)
        auth.grid(row=1, column=3, sticky="ew", padx=6, pady=5)
        labeled_entry(frame, "Contraseña", self.password, 2, 0, show="*")
        labeled_entry(frame, "Archivo de clave SSH", self.key_file, 3, 0, width=35)
        ttk.Button(frame, text="Examinar", command=self._browse_key).grid(row=3, column=4, padx=6)
        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=5, sticky="w", pady=(12, 0))
        self.connect_button = ttk.Button(actions, text="CONECTAR / OBTENER PERFIL", command=self.on_collect)
        self.connect_button.pack(side="left")
        ttk.Button(actions, text="MODO DEMOSTRACIÓN", command=self.on_demo).pack(side="left", padx=8)
        ttk.Button(actions, text="CARGAR PERFIL JSON", command=self.on_import).pack(side="left")
        ttk.Label(self, textvariable=self.status).grid(row=4, column=0, sticky="w", pady=12)
        security = ttk.LabelFrame(self, text="SEGURIDAD", padding=12)
        security.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(security, text="✓ SSH de solo lectura    ✓ Sin comandos arbitrarios    ✓ Credenciales no almacenadas\n✓ Se rechazan hosts desconocidos; agrega su huella verificada a known_hosts antes de conectar").pack(anchor="w")

    def _browse_key(self):
        path = filedialog.askopenfilename(title="Seleccionar clave privada SSH")
        if path:
            self.key_file.set(path)

    def values(self) -> dict[str, str]:
        return {"host": self.host.get().strip(), "port": self.port.get().strip(), "username": self.username.get().strip(), "password": self.password.get(), "key_file": self.key_file.get().strip(), "auth": self.auth.get()}

    def set_status(self, value: str):
        self.status.set(value)

    def busy(self, value: bool):
        self.connect_button.configure(state="disabled" if value else "normal")
