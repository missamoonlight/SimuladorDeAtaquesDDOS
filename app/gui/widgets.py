from __future__ import annotations

import tkinter as tk
from tkinter import ttk


PALETTE = {
    "bg": "#0b1110",
    "panel": "#111c19",
    "panel2": "#172622",
    "green": "#54e38e",
    "muted": "#89a79a",
    "text": "#d9f6e4",
    "danger": "#ff6b6b",
    "amber": "#f0c674",
}


def configure_style(root: tk.Tk) -> None:
    root.configure(bg=PALETTE["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=PALETTE["bg"])
    style.configure("Panel.TFrame", background=PALETTE["panel"])
    style.configure("TLabel", background=PALETTE["bg"], foreground=PALETTE["text"], font=("Segoe UI", 10))
    style.configure("Title.TLabel", background=PALETTE["bg"], foreground=PALETTE["green"], font=("Consolas", 20, "bold"))
    style.configure("Subtitle.TLabel", background=PALETTE["bg"], foreground=PALETTE["muted"], font=("Segoe UI", 10))
    style.configure("TLabelframe", background=PALETTE["panel"], foreground=PALETTE["green"], bordercolor="#315a48")
    style.configure("TLabelframe.Label", background=PALETTE["panel"], foreground=PALETTE["green"], font=("Consolas", 10, "bold"))
    style.configure("TButton", background="#1d4d38", foreground=PALETTE["text"], padding=(10, 6), borderwidth=0)
    style.map("TButton", background=[("active", "#2b7652"), ("disabled", "#26352e")])
    style.configure("TEntry", fieldbackground="#0f1916", foreground=PALETTE["text"], insertcolor=PALETTE["green"])
    style.configure("TCombobox", fieldbackground="#0f1916", foreground=PALETTE["text"])
    style.configure("Treeview", background="#0f1916", fieldbackground="#0f1916", foreground=PALETTE["text"], rowheight=26)
    style.configure("Treeview.Heading", background="#1d4d38", foreground=PALETTE["text"], font=("Consolas", 9, "bold"))
    style.configure("TNotebook", background=PALETTE["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=PALETTE["panel"], foreground=PALETTE["muted"], padding=(14, 7))
    style.map("TNotebook.Tab", background=[("selected", "#1d4d38")], foreground=[("selected", PALETTE["green"])])


def labeled_entry(parent, label: str, variable: tk.Variable, row: int, column: int, show: str | None = None, width: int = 20) -> ttk.Entry:
    ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=6, pady=5)
    entry = ttk.Entry(parent, textvariable=variable, width=width, show=show or "")
    entry.grid(row=row, column=column + 1, sticky="ew", padx=6, pady=5)
    return entry


def set_text(widget: tk.Text, value: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", tk.END)
    widget.insert("1.0", value)
    widget.configure(state="disabled")
