from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from aplicacion.interfaz.componentes_interfaz import PALETTE


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
        self.status = tk.StringVar(value="Listo.")
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="CONEXIÓN Y PERFIL", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(12, 8))
        frame = ttk.LabelFrame(self, text="CONEXIÓN SSH", padding=14)
        frame.grid(row=1, column=0, sticky="new", pady=(8, 0))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        ttk.Label(frame, text="Host / Dirección IP").grid(row=0, column=0, sticky="w", padx=6, pady=5)
        ttk.Entry(frame, textvariable=self.host).grid(row=0, column=1, sticky="ew", padx=6, pady=5)
        ttk.Label(frame, text="Puerto SSH").grid(row=0, column=2, sticky="w", padx=6, pady=5)
        ttk.Entry(frame, textvariable=self.port, width=8).grid(row=0, column=3, sticky="ew", padx=6, pady=5)
        ttk.Label(frame, text="Usuario").grid(row=1, column=0, sticky="w", padx=6, pady=5)
        ttk.Entry(frame, textvariable=self.username).grid(row=1, column=1, columnspan=3, sticky="ew", padx=6, pady=5)
        ttk.Label(frame, text="Método de autenticación").grid(row=2, column=0, sticky="w", padx=6, pady=5)
        auth = ttk.Combobox(frame, textvariable=self.auth, values=("Contraseña", "Clave SSH"), state="readonly", width=17)
        auth.grid(row=2, column=1, columnspan=3, sticky="ew", padx=6, pady=5)
        self.password_label = ttk.Label(frame, text="Contraseña")
        self.password_label.grid(row=3, column=0, sticky="w", padx=6, pady=5)
        self.password_entry = ttk.Entry(frame, textvariable=self.password, show="*")
        self.password_entry.grid(row=3, column=1, columnspan=3, sticky="ew", padx=6, pady=5)
        self.key_label = ttk.Label(frame, text="Archivo de clave SSH")
        self.key_entry = ttk.Entry(frame, textvariable=self.key_file)
        self.key_button = ttk.Button(frame, text="Examinar…", command=self._browse_key)
        self.key_label.grid(row=3, column=0, sticky="w", padx=6, pady=5)
        self.key_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=6, pady=5)
        self.key_button.grid(row=3, column=3, sticky="w", padx=6, pady=5)
        self.auth_help = ttk.Label(frame, text="Usa la contraseña de la cuenta del servidor.", foreground=PALETTE["muted"], wraplength=460)
        self.auth_help.grid(row=4, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 5))
        auth.bind("<<ComboboxSelected>>", self._auth_changed)
        self._auth_changed()
        actions = ttk.Frame(frame)
        actions.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.connect_button = ttk.Button(actions, text="CONECTAR Y OBTENER PERFIL", command=self.on_collect, style="Primary.TButton")
        self.connect_button.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.demo_button = ttk.Button(actions, text="USAR DEMOSTRACI\u00d3N", command=self.on_demo)
        self.demo_button.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.import_button = ttk.Button(actions, text="CARGAR PERFIL JSON", command=self.on_import)
        self.import_button.grid(row=1, column=1, sticky="ew", padx=(4, 0))
        guide = ttk.LabelFrame(self, text="CÓMO EMPEZAR", padding=(12, 10))
        guide.grid(row=2, column=0, sticky="new", pady=(14, 0))
        for row, text in enumerate((
            "1. Conecta por SSH o carga un perfil guardado.",
            "2. Revisa los recursos detectados en el panel Perfil.",
            "3. Continúa a Simulación para configurar el escenario.",
        )):
            ttk.Label(guide, text=text, style="Subtitle.TLabel", wraplength=460).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Label(guide, text="La simulación usa un modelo local; no envía tráfico al servidor.", wraplength=460).grid(row=3, column=0, sticky="w", pady=(9, 2))
        ttk.Label(self, textvariable=self.status, style="Subtitle.TLabel", wraplength=480).grid(row=3, column=0, sticky="sw", pady=(12, 8))

    def _browse_key(self):
        path = filedialog.askopenfilename(
            title="Seleccionar clave privada SSH",
            filetypes=(("Claves privadas SSH", "*.pem *.key id_*"), ("Todos los archivos", "*.*")),
        )
        if path:
            self.key_file.set(path)

    def _auth_changed(self, _event=None):
        if self.auth.get() == "Clave SSH":
            self.password_label.grid_remove()
            self.password_entry.grid_remove()
            self.key_label.grid()
            self.key_entry.grid()
            self.key_button.grid()
            self.auth_help.configure(text="Selecciona tu clave privada. Su clave pública correspondiente debe estar autorizada en el servidor.")
        else:
            self.key_label.grid_remove()
            self.key_entry.grid_remove()
            self.key_button.grid_remove()
            self.password_label.grid()
            self.password_entry.grid()
            self.auth_help.configure(text="Usa la contraseña de la cuenta del servidor.")

    def values(self) -> dict[str, str]:
        return {"host": self.host.get().strip(), "port": self.port.get().strip(), "username": self.username.get().strip(), "password": self.password.get(), "key_file": self.key_file.get().strip(), "auth": self.auth.get()}

    def set_status(self, value: str):
        self.status.set(value)

    def busy(self, value: bool):
        state = "disabled" if value else "normal"
        for button in (self.connect_button, self.demo_button, self.import_button):
            button.configure(state=state)
