from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from app.gui.widgets import set_text
from app.models.server_profile import ServerProfile
from app.reports.report_generator import save_profile


class ProfileView(ttk.Frame):
    def __init__(self, parent, on_continue, on_back):
        super().__init__(parent)
        self.profile: ServerProfile | None = None
        self.on_continue = on_continue
        self.on_back = on_back
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="PERFIL DEL SERVIDOR", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(12, 10))
        self.summary = tk.Text(self, height=15, state="disabled", bg="#0f1916", fg="#d9f6e4", insertbackground="#54e38e", relief="flat", font=("Consolas", 10))
        self.summary.grid(row=1, column=0, sticky="ew")
        frame = ttk.LabelFrame(self, text="DISCO Y RED", padding=8)
        frame.grid(row=2, column=0, sticky="nsew", pady=10)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("tipo", "detalle"), show="headings")
        self.tree.heading("tipo", text="TIPO")
        self.tree.heading("detalle", text="DETALLE")
        self.tree.column("tipo", width=160)
        self.tree.column("detalle", width=700)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview).grid(row=0, column=1, sticky="ns")
        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="w", pady=(0, 10))
        ttk.Button(actions, text="GUARDAR PERFIL", command=self.save).pack(side="left")
        ttk.Button(actions, text="VOLVER", command=on_back).pack(side="left", padx=8)
        ttk.Button(actions, text="CONTINUAR A SIMULACIÓN", command=on_continue).pack(side="left")

    def set_profile(self, profile: ServerProfile):
        self.profile = profile
        set_text(self.summary, profile.readable_text())
        for item in self.tree.get_children():
            self.tree.delete(item)
        for disk in profile.disks:
            self.tree.insert("", "end", values=("DISCO", " | ".join(f"{key}: {value}" for key, value in disk.items())))
        for interface in profile.network_interfaces:
            self.tree.insert("", "end", values=("RED", f"{interface.name} | {interface.speed_mbps:g} Mbps | RX {interface.rx_bytes} | TX {interface.tx_bytes}"))

    def save(self):
        if not self.profile:
            return
        destination = filedialog.askdirectory(title="Carpeta para guardar el perfil")
        if not destination:
            return
        json_path, text_path = save_profile(self.profile, Path(destination))
        messagebox.showinfo("Perfil guardado", f"JSON: {json_path}\nTXT: {text_path}")
