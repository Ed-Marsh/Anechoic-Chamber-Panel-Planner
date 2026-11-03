"""Tkinter front end for the chamber planner.

Everything here goes through chamber.core and chamber.exporters, the same code the
command line uses, so a config gives identical files from either.

Run with:  python -m chamber.gui
"""
import copy
import json
import math
import os
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from chamber import __version__, core, exporters, render

APP_NAME = "Chamber Planner"
RECOMPUTE_DELAY_MS = 300
DEFAULT_VIEW = (25, -55)          # elevation, azimuth: same camera as the PNG preview
DEFAULT_ZOOM = 1.2
ERROR_COLOUR = "#b00020"
INT_RE = re.compile(r"^[+-]?\d+$")

# (group title, [(config path, label, unit, kind)]).  kind: num | opt (blank allowed) |
# bool | choice.  Every key in the README's configuration table has a field.
FORM = [
    ("Internal size", [
        ("internal.length", "Length (x)", "mm", "num"),
        ("internal.width", "Width (y)", "mm", "num"),
        ("internal.height", "Height (z)", "mm", "num"),
    ]),
    ("Sheet", [
        ("sheet.length", "Length", "mm", "num"),
        ("sheet.width", "Width", "mm", "num"),
    ]),
    ("Panel thickness", [
        ("board_thickness", "Board thickness", "mm", "num"),
        ("steel_thickness", "Steel, per face", "mm", "num"),
    ]),
    ("Board thickness override (blank = use the board thickness)", [
        ("thickness_override." + n, n.capitalize(), "mm", "opt") for n in core.SURFACES
    ]),
    ("Hat & flat", [
        ("hat_flat.hat_width", "Hat width", "mm", "num"),
        ("hat_flat.hat_depth", "Hat depth", "mm", "num"),
        ("hat_flat.flat_width", "Flat width", "mm", "num"),
        ("hat_flat.flat_thickness", "Flat thickness", "mm", "num"),
        ("hat_flat.stock_length", "Stock length", "mm", "num"),
        ("hat_flat.end_clearance", "End clearance", "mm", "num"),
        ("hat_flat.screw_pitch", "Screw pitch (0 = none)", "mm", "num"),
        ("hat_flat.draw_in_3d", "Draw hat & flat in 3D", "", "bool"),
    ]),
    ("Layout", [
        ("corner_joints", "Hat & flat on corners and edges", "", "bool"),
        ("stagger", "Stagger (fraction of sheet)", "", "num"),
        ("kerf", "Saw kerf", "mm", "num"),
        ("min_panel", "Minimum panel size (0 = off)", "mm", "num"),
        ("explode_mm", "Explode distance", "mm", "num"),
    ]),
    ("Door", [
        ("door.enabled", "Door opening", "", "bool"),
        ("door.wall", "Wall", "", "choice"),
        ("door.offset", "Offset from west/south face", "mm", "num"),
        ("door.width", "Width", "mm", "num"),
        ("door.height", "Height", "mm", "num"),
    ]),
]

EXPORT_ITEMS = [
    ("panel_cutlist", "Panel cut list (CSV)", [("CSV", "*.csv")]),
    ("hatflat_cutlist", "Hat & flat cut list (CSV)", [("CSV", "*.csv")]),
    ("bom", "Bill of materials (CSV)", [("CSV", "*.csv")]),
    ("summary", "Summary (text)", [("Text", "*.txt")]),
    ("dxf_2d", "2D drawing (DXF)", [("DXF", "*.dxf")]),
    ("dxf_3d", "3D drawing, assembled (DXF)", [("DXF", "*.dxf")]),
    ("dxf_3d_exploded", "3D drawing, exploded (DXF)", [("DXF", "*.dxf")]),
    ("png", "3D preview image (PNG)", [("PNG", "*.png")]),
]


# ---------------------------------------------------------------- helpers
def get_in(d, path):
    for key in path.split("."):
        if not isinstance(d, dict) or key not in d:
            return None
        d = d[key]
    return d


def set_in(d, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        if not isinstance(d.get(key), dict):
            d[key] = {}
        d = d[key]
    d[keys[-1]] = value


def del_in(d, path):
    keys = path.split(".")
    for key in keys[:-1]:
        d = d.get(key)
        if not isinstance(d, dict):
            return
    d.pop(keys[-1], None)


def parse_number(text):
    """int for whole numbers (so saved JSON reads 4000, not 4000.0), else float; None if invalid."""
    text = text.strip()
    try:
        value = int(text) if INT_RE.match(text) else float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def settings_path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "ChamberPlanner", "settings.json")


def load_settings(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass   # remembering the window is a convenience, never worth an error dialog


def make_table(parent, columns, widths=None, height=10):
    """A ttk.Treeview with scrollbars. columns: list of (id, heading, width, anchor)."""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height)
    for cid, head, width, anchor in columns:
        tree.heading(cid, text=head)
        tree.column(cid, width=width, anchor=anchor, stretch=True)
    ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    xs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, tree


def fill_table(tree, rows):
    tree.delete(*tree.get_children())
    for row in rows:
        tree.insert("", "end", values=["" if v is None else v for v in row])


class Field:
    def __init__(self, path, kind, var, entry, err):
        self.path, self.kind, self.var, self.entry, self.err = path, kind, var, entry, err


# ---------------------------------------------------------------- application
class ChamberApp(tk.Tk):
    def __init__(self, settings_file=None):
        super().__init__()
        self.settings_file = settings_file or settings_path()
        self.settings = load_settings(self.settings_file)
        self.base_cfg = copy.deepcopy(core.EXAMPLE)    # keeps keys the form has no field for
        self.cfg_path = None
        self.modified = False
        self._loading = False
        self._after = None
        self._after3d = None
        self.model = None
        self.plan = None
        self.fields = {}
        self.field_issues = {}
        self.zoom = DEFAULT_ZOOM

        self.title(APP_NAME)
        self.minsize(1000, 640)
        self.geometry(self._initial_geometry())
        ttk.Style(self).configure("Error.TEntry", foreground=ERROR_COLOUR)

        self._build_menu()
        self._build_body()
        self.status = ttk.Label(self, anchor="w", relief="sunken", padding=(6, 2))
        self.status.pack(side="bottom", fill="x")
        self.body.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Map>", self._on_first_map)
        for seq, fn in (("<Control-o>", self.open_config), ("<Control-s>", self.save_config),
                        ("<Control-S>", self.save_config_as), ("<Control-e>", self.export_all)):
            self.bind(seq, lambda e, fn=fn: fn())
        self.set_config(self.base_cfg)

    # ---- window state ------------------------------------------------
    def _initial_geometry(self):
        geo = self.settings.get("geometry", "")
        m = re.match(r"^(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?$", geo if isinstance(geo, str) else "")
        w, h = (int(m.group(1)), int(m.group(2))) if m else (1280, 820)
        w, h = max(1000, min(w, self.winfo_screenwidth())), max(640, min(h, self.winfo_screenheight()))
        pos = ""
        if m and m.group(3):
            x, y = int(m.group(3)), int(m.group(4))
            # Ignore a saved position that is now off-screen (monitor unplugged).
            if -50 <= x <= self.winfo_screenwidth() - 150 and -10 <= y <= self.winfo_screenheight() - 100:
                pos = f"{x:+d}{y:+d}"
        return f"{w}x{h}{pos}"

    def _on_first_map(self, event):
        # The right pane's tables request more width than the window has, so pin the
        # sash once the window exists: the form keeps its width, the tabs take the rest.
        if event.widget is self:
            self.unbind("<Map>")
            self.after(20, lambda: self.body.sashpos(0, 430))

    def remember_folder(self, path):
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if folder:
            self.settings["last_dir"] = folder

    def last_dir(self):
        d = self.settings.get("last_dir")
        return d if isinstance(d, str) and os.path.isdir(d) else os.getcwd()

    # ---- menu --------------------------------------------------------
    def _build_menu(self):
        bar = tk.Menu(self)
        fm = tk.Menu(bar, tearoff=0)
        fm.add_command(label="New (example chamber)", command=self.new_config)
        fm.add_command(label="Open config…", accelerator="Ctrl+O", command=self.open_config)
        fm.add_command(label="Save config", accelerator="Ctrl+S", command=self.save_config)
        fm.add_command(label="Save config as…", accelerator="Ctrl+Shift+S", command=self.save_config_as)
        fm.add_separator()
        fm.add_command(label="Export all…", accelerator="Ctrl+E", command=self.export_all)
        single = tk.Menu(fm, tearoff=0)
        for key, label, _ in EXPORT_ITEMS:
            single.add_command(label=label, command=lambda k=key: self.export_one(k))
        fm.add_cascade(label="Export single item", menu=single)
        fm.add_separator()
        fm.add_command(label="Exit", command=self.on_close)
        bar.add_cascade(label="File", menu=fm)
        hm = tk.Menu(bar, tearoff=0)
        hm.add_command(label=f"About {APP_NAME}", command=self.about)
        bar.add_cascade(label="Help", menu=hm)
        self.config(menu=bar)

    def about(self):
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} {__version__}\n\nPanel and hat & flat planner for anechoic chambers.\n"
            "All dimensions in millimetres.\n\n"
            "Plans the panel layout only; it does not check structural adequacy.")

    # ---- layout ------------------------------------------------------
    def _build_body(self):
        self.body = ttk.PanedWindow(self, orient="horizontal")
        left = ttk.Frame(self.body)
        right = ttk.Frame(self.body)
        self.body.add(left, weight=0)
        self.body.add(right, weight=1)
        self._build_form(left)
        self._build_tabs(right)

    def _build_form(self, parent):
        canvas = tk.Canvas(parent, width=400, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(8, 4))
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def wheel(e):
            canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self.general_error = ttk.Label(inner, foreground=ERROR_COLOUR, wraplength=360, justify="left")
        self.general_error.pack(fill="x", pady=(0, 4))
        for title, rows in FORM:
            box = ttk.LabelFrame(inner, text=title, padding=(6, 4))
            box.pack(fill="x", pady=3)
            box.columnconfigure(1, weight=1)
            for r, (path, label, unit, kind) in enumerate(rows):
                self._add_field(box, 2 * r, path, label, unit, kind)

    def _add_field(self, box, row, path, label, unit, kind):
        if kind == "bool":
            var = tk.BooleanVar()
            w = ttk.Checkbutton(box, text=label, variable=var)
            w.grid(row=row, column=0, columnspan=3, sticky="w", pady=1)
        else:
            var = tk.StringVar()
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=1)
            if kind == "choice":
                w = ttk.Combobox(box, textvariable=var, values=core.WALLS, state="readonly", width=9)
            else:
                w = ttk.Entry(box, textvariable=var, width=11, justify="right")
            w.grid(row=row, column=1, sticky="e", padx=4, pady=1)
            ttk.Label(box, text=unit, width=3).grid(row=row, column=2, sticky="w")
        err = ttk.Label(box, foreground=ERROR_COLOUR, wraplength=320, justify="left",
                        font=("TkDefaultFont", 8))
        err.grid(row=row + 1, column=0, columnspan=3, sticky="w")
        err.grid_remove()
        var.trace_add("write", self._on_edit)
        self.fields[path] = Field(path, kind, var, w, err)

    def _build_tabs(self, parent):
        self.banner = ttk.Label(parent, foreground=ERROR_COLOUR, padding=(6, 3))
        self.banner.pack(fill="x")
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True)
        self.notebook = nb
        self._build_3d_tab(nb)
        self._build_summary_tab(nb)
        self._build_cutlist_tab(nb)
        self._build_hatflat_tab(nb)
        self._build_2d_tab(nb)

    # ---- 3D tab ------------------------------------------------------
    def _build_3d_tab(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="3D view")
        bar = ttk.Frame(tab, padding=(6, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Explode").grid(row=0, column=0, sticky="w")
        self.explode_var = tk.DoubleVar(value=0)
        self.explode_scale = ttk.Scale(bar, from_=0, to=300, variable=self.explode_var,
                                       command=lambda v: self.schedule_redraw3d())
        self.explode_scale.grid(row=0, column=1, sticky="ew", padx=6)
        self.explode_label = ttk.Label(bar, text="0 mm", width=8)
        self.explode_label.grid(row=0, column=2)
        ttk.Button(bar, text="Reset view", command=self.reset_view).grid(row=0, column=3, padx=6)
        bar.columnconfigure(1, weight=1)

        shown = ttk.Frame(tab, padding=(6, 0))
        shown.pack(fill="x")
        ttk.Label(shown, text="Show:").pack(side="left")
        self.hf_var = tk.BooleanVar(value=True)
        self.hf_check = ttk.Checkbutton(shown, text="Hat & flat", variable=self.hf_var,
                                        command=self.schedule_redraw3d)
        self.hf_check.pack(side="left", padx=(6, 12))
        self.surface_vars = {}
        for n in core.SURFACES:
            v = tk.BooleanVar(value=True)
            self.surface_vars[n] = v
            ttk.Checkbutton(shown, text=n.capitalize(), variable=v,
                            command=self.schedule_redraw3d).pack(side="left", padx=3)

        self.fig3d = Figure(figsize=(7, 5.5), dpi=100)
        self.ax3d = self.fig3d.add_subplot(111, projection="3d")
        self.ax3d.view_init(*DEFAULT_VIEW)
        self.canvas3d = FigureCanvasTkAgg(self.fig3d, master=tab)
        self.canvas3d.get_tk_widget().pack(fill="both", expand=True)
        self.canvas3d.mpl_connect("scroll_event", self._on_scroll)
        ttk.Label(tab, padding=(6, 2), foreground="#666666",
                  text="Drag to rotate, right-drag or scroll to zoom. Hiding a surface also hides "
                       "its hat & flat, so you can look inside.").pack(fill="x")

    def schedule_redraw3d(self):
        if self._after3d is None:
            self._after3d = self.after(40, self.redraw3d)

    def reset_view(self):
        self.zoom = DEFAULT_ZOOM
        self.ax3d.view_init(*DEFAULT_VIEW)
        self.redraw3d()

    def _on_scroll(self, event):
        self.zoom = max(0.3, min(4.0, self.zoom * (1.1 if event.button == "up" else 1 / 1.1)))
        self.redraw3d()

    def redraw3d(self):
        self._after3d = None
        if not self.model:
            return
        ax = self.ax3d
        elev, azim = ax.elev, ax.azim
        ax.clear()
        explode = round(self.explode_var.get())
        self.explode_label.config(text=f"{explode} mm")
        hidden = {n for n, v in self.surface_vars.items() if not v.get()}
        render.draw_chamber(ax, self.model, explode, hidden, self.hf_var.get(),
                            merged=True, margin=100, zoom=self.zoom)
        ax.view_init(elev, azim)
        self.canvas3d.draw_idle()

    # ---- tables ------------------------------------------------------
    def _build_summary_tab(self, nb):
        tab = ttk.Frame(nb, padding=6)
        nb.add(tab, text="Summary / BOM")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)
        box = ttk.LabelFrame(tab, text="Summary", padding=4)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        f, self.summary_tree = make_table(box, [("item", "Item", 220, "w"), ("value", "Value", 420, "w")],
                                          height=9)
        f.grid(sticky="nsew")
        ttk.Label(tab, text="Bill of materials", padding=(0, 8, 0, 2)).grid(row=1, column=0, sticky="sw")
        f, self.bom_tree = make_table(tab, [("item", "Item", 300, "w"), ("size", "Size", 160, "w"),
                                            ("notes", "Notes", 140, "w"), ("qty", "Qty", 60, "e"),
                                            ("unit", "Unit", 60, "w")], height=8)
        f.grid(row=2, column=0, sticky="nsew")
        ttk.Label(tab, text="Panel thickness by surface", padding=(0, 8, 0, 2)).grid(row=3, column=0, sticky="sw")
        f, self.thick_tree = make_table(tab, [("surface", "Surface", 120, "w"),
                                              ("board", "Board (mm)", 100, "e"),
                                              ("total", "Total with steel (mm)", 160, "e")], height=6)
        f.grid(row=4, column=0, sticky="nsew")
        tab.rowconfigure(2, weight=1)
        tab.rowconfigure(4, weight=1)

    def _build_cutlist_tab(self, nb):
        tab = ttk.Frame(nb, padding=6)
        nb.add(tab, text="Panel cut list")
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        cols = [(c, c, 70 if c not in ("surface", "type") else 80, "e" if c not in ("id", "surface", "type") else "w")
                for c in core.PANEL_COLS]
        f, self.panel_tree = make_table(tab, cols)
        f.grid(sticky="nsew")

    def _build_hatflat_tab(self, nb):
        tab = ttk.Frame(nb, padding=6)
        nb.add(tab, text="Hat & flat cut list")
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        cols = [(c, c, 110, "w" if c in ("joint", "surface") else "e") for c in core.HATFLAT_COLS]
        f, self.hf_tree = make_table(tab, cols)
        f.grid(sticky="nsew")
        self.hf_footer = ttk.Label(tab, padding=(0, 6, 0, 0), justify="left", wraplength=800)
        self.hf_footer.grid(row=1, column=0, sticky="w")

    def _build_2d_tab(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Surface layout")
        bar = ttk.Frame(tab, padding=(6, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Surface").pack(side="left")
        self.surface_var = tk.StringVar(value="south")
        cb = ttk.Combobox(bar, textvariable=self.surface_var, values=core.SURFACES,
                          state="readonly", width=10)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.redraw2d())
        self.fig2d = Figure(figsize=(7, 5), dpi=100)
        self.ax2d = self.fig2d.add_subplot(111)
        self.canvas2d = FigureCanvasTkAgg(self.fig2d, master=tab)
        self.canvas2d.get_tk_widget().pack(fill="both", expand=True)

    def redraw2d(self):
        if not self.model:
            return
        self.ax2d.clear()
        render.draw_surface(self.ax2d, self.model, self.surface_var.get())
        self.fig2d.tight_layout()
        self.canvas2d.draw_idle()

    def refresh_views(self):
        plan, m = self.plan, self.model
        cfg = m["cfg"]
        d = cfg.get("door")
        rows = [("Internal size", f"{m['L']} x {m['W']} x {m['H']} mm"),
                ("External size", "{:.1f} x {:.1f} x {:.1f} mm".format(*plan["external"])),
                ("Door", f"{m['door']['wall']} wall, {d['width']} x {d['height']} mm, offset {d['offset']} mm"
                 if m["door"] else "none"),
                ("Panels", f"{plan['full_count']} full + {plan['cut_count']} cut pieces"),
                ("Sheets", f"{plan['sheets_for_cuts']} for cut pieces + {plan['full_count']} whole "
                           f"= {plan['total_sheets']} total"),
                ("Hat & flat run", f"{plan['total_hf'] / 1000:.2f} m each"),
                ("Hat & flat stock", f"{plan['bar_count']} x {plan['stock']} mm bars each"),
                ("Fasteners (est.)", plan["fasteners"])]
        rows += [("Warning", w) for w in plan["warnings"]]
        fill_table(self.summary_tree, rows)
        fill_table(self.bom_tree, plan["bom"])
        fill_table(self.thick_tree, plan["thickness_rows"])
        fill_table(self.panel_tree, [[r[c] for c in core.PANEL_COLS] for r in plan["panel_rows"]])
        fill_table(self.hf_tree, plan["hatflat_rows"])
        self.hf_footer.config(
            text=f"Stock bars needed (each of hat AND flat): {plan['bar_count']} x {plan['stock']} mm\n"
                 "Offcut per bar (mm): " + ", ".join(f"{o:g}" for o in plan["bar_offcuts"]))
        # explode slider follows the config's explode_mm
        top = max(float(cfg["explode_mm"]), 1.0)
        self.explode_scale.config(to=top)
        if self.explode_var.get() > top:
            self.explode_var.set(top)
        draws_hf = cfg["hat_flat"]["draw_in_3d"]
        self.hf_check.state(["!disabled"] if draws_hf else ["disabled"])
        self.redraw3d()
        self.redraw2d()

    # ---- form <-> config ---------------------------------------------
    def set_config(self, raw):
        """Load a config dict into the form (missing keys take defaults, unknown keys are
        kept and written back on save)."""
        cfg = core.normalise_config(raw)
        self._loading = True
        try:
            self.base_cfg = copy.deepcopy(raw)
            door = cfg.get("door") or {}
            example_door = core.EXAMPLE["door"]
            for path, f in self.fields.items():
                if path == "door.enabled":
                    f.var.set(bool(cfg.get("door")))
                    continue
                value = get_in(door if path.startswith("door.") else cfg,
                               path[5:] if path.startswith("door.") else path)
                if value is None and path.startswith("door."):
                    value = example_door.get(path[5:])
                if f.kind == "bool":
                    f.var.set(bool(value))
                else:
                    f.var.set("" if value is None else str(value))
        finally:
            self._loading = False
        self.modified = False
        self.recompute_now()
        self._update_title()

    def form_to_cfg(self):
        """Build a config from the form. Returns (cfg, errors) where errors maps a field
        path to a message for text that is not a number."""
        cfg = copy.deepcopy(self.base_cfg)
        errors = {}
        door_on = self.fields["door.enabled"].var.get()
        for path, f in self.fields.items():
            if path == "door.enabled" or (path.startswith("door.") and not door_on):
                continue
            if f.kind in ("bool", "choice"):
                set_in(cfg, path, f.var.get())
                continue
            text = f.var.get().strip()
            if not text and f.kind == "opt":
                del_in(cfg, path)
                continue
            value = parse_number(text) if text else None
            if value is None:
                errors[path] = "Enter a number" if text else "Enter a value"
            else:
                set_in(cfg, path, value)
        if not door_on:
            cfg.pop("door", None)
        return cfg, errors

    def _on_edit(self, *_):
        if self._loading:
            return
        self.modified = True
        self._update_title()
        if self._after is not None:
            self.after_cancel(self._after)
        self._after = self.after(RECOMPUTE_DELAY_MS, self.recompute_now)

    def recompute_now(self):
        """Rebuild from the form. On any error the last good view stays on screen."""
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        cfg, parse_errors = self.form_to_cfg()
        issues = {p: m for p, m in parse_errors.items()}
        general = []
        if not issues:
            _, found = core.validate_config(cfg)
            for path, msg in found:
                if path in self.fields:
                    issues.setdefault(path, msg)
                else:
                    general.append(f"{path + ': ' if path else ''}{msg}")
        if not issues and not general:
            try:
                model = core.build(cfg)
                plan = core.compute_plan(model)
            except Exception as e:   # a piece that cannot be packed, etc.
                general.append(str(e))
            else:
                self.model, self.plan = model, plan
        self.show_issues(issues, general)
        if self.model and not issues and not general:
            self.refresh_views()
            warned = len(self.plan["warnings"])
            self.set_status(f"{self.plan['total_sheets']} sheets, "
                            f"{self.plan['total_hf'] / 1000:.2f} m of hat & flat"
                            + (f"  |  {warned} undersize piece{'s' if warned != 1 else ''}, "
                               "see the Summary tab" if warned else ""))
        else:
            self.set_status("Fix the highlighted fields" if issues else (general[0] if general else ""))
        return not issues and not general

    def show_issues(self, issues, general):
        for path, f in self.fields.items():
            msg = issues.get(path)
            if msg:
                f.err.config(text=msg)
                f.err.grid()
            else:
                f.err.grid_remove()
            if f.kind not in ("bool", "choice"):
                f.entry.configure(style="Error.TEntry" if msg else "TEntry")
        self.general_error.config(text="\n".join(general))
        bad = bool(issues or general)
        self.banner.config(text="Showing the last valid layout. Fix the highlighted field(s) to update it."
                           if bad and self.model else "")
        self.field_issues = issues

    def set_status(self, text):
        self.status.config(text=text)

    def _update_title(self):
        name = os.path.basename(self.cfg_path) if self.cfg_path else "untitled"
        self.title(f"{APP_NAME} - {name}{' *' if self.modified else ''}")

    # ---- file menu ---------------------------------------------------
    def confirm_discard(self):
        if not self.modified:
            return True
        ans = messagebox.askyesnocancel(APP_NAME, "Save changes to the current configuration?")
        if ans is None:
            return False
        return self.save_config() if ans else True

    def new_config(self):
        if self.confirm_discard():
            self.cfg_path = None
            self.set_config(copy.deepcopy(core.EXAMPLE))

    def open_config(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Open configuration", initialdir=self.last_dir(),
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")])
        if path:
            self.load_config_file(path)

    def load_config_file(self, path):
        try:
            with open(path) as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("the top level of the file must be a JSON object")
            self.set_config(raw)
        except (OSError, ValueError) as e:
            messagebox.showerror(APP_NAME, f"Could not open {os.path.basename(path)}:\n{e}")
            return False
        self.cfg_path = path
        self.remember_folder(path)
        self._update_title()
        return True

    def save_config(self):
        if not self.cfg_path:
            return self.save_config_as()
        return self.write_config(self.cfg_path)

    def save_config_as(self):
        path = filedialog.asksaveasfilename(
            title="Save configuration", initialdir=self.last_dir(), defaultextension=".json",
            initialfile=os.path.basename(self.cfg_path) if self.cfg_path else "chamber_config.json",
            filetypes=[("JSON config", "*.json")])
        return bool(path) and self.write_config(path)

    def write_config(self, path):
        cfg, errors = self.form_to_cfg()
        if errors:
            messagebox.showwarning(APP_NAME, "Fix the highlighted fields before saving.")
            return False
        try:
            with open(path, "w") as f:
                json.dump(cfg, f, indent=2)
                f.write("\n")
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Could not save {path}:\n{e.strerror}")
            return False
        self.cfg_path = path
        self.base_cfg = cfg
        self.modified = False
        self.remember_folder(path)
        self._update_title()
        self.set_status(f"Saved {path}")
        return True

    def _ready_to_export(self):
        if not self.recompute_now() or not self.model:
            messagebox.showwarning(APP_NAME, "Fix the highlighted fields before exporting.")
            return False
        return True

    def export_all(self):
        if not self._ready_to_export():
            return
        folder = filedialog.askdirectory(title="Export all files to", initialdir=self.last_dir())
        if not folder:
            return
        try:
            res = exporters.export_all(self.model, folder, self.plan)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Export failed:\n{e}")
            return
        self.remember_folder(folder)
        files = [os.path.basename(p) for p in res["paths"].values() if p] + \
                [exporters.FILES[k] for k in ("panel_cutlist", "hatflat_cutlist", "bom", "summary")]
        self.set_status(f"Exported to {folder}")
        messagebox.showinfo(APP_NAME, f"Wrote {len(files)} files to\n{folder}")

    def export_one(self, key):
        if not self._ready_to_export():
            return
        label, types = next((lbl, t) for k, lbl, t in EXPORT_ITEMS if k == key)
        path = filedialog.asksaveasfilename(
            title=f"Export {label}", initialdir=self.last_dir(), initialfile=exporters.FILES[key],
            defaultextension=os.path.splitext(exporters.FILES[key])[1], filetypes=types)
        if not path:
            return
        folder, name = os.path.split(path)
        m, plan = self.model, self.plan
        try:
            if key == "panel_cutlist":
                exporters.write_panel_cutlist(plan, path)
            elif key == "hatflat_cutlist":
                exporters.write_hatflat_cutlist(plan, path)
            elif key == "bom":
                exporters.write_bom(plan, path)
            elif key == "summary":
                exporters.write_summary(plan, path)
            elif key == "dxf_2d":
                exporters.draw(m, folder, name)
            elif key == "dxf_3d":
                exporters.draw3d(m, folder, name=name)
            elif key == "dxf_3d_exploded":
                exporters.draw3d(m, folder, explode=m["cfg"]["explode_mm"], name=name)
            elif key == "png":
                exporters.preview(m, folder, name=name)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Export failed:\n{e}")
            return
        self.remember_folder(path)
        self.set_status(f"Exported {path}")

    def on_close(self):
        if not self.confirm_discard():
            return
        self.settings["geometry"] = self.geometry()
        save_settings(self.settings_file, self.settings)
        self.destroy()


def selftest(outdir):
    """Start the real app, load the example, recompute and export everything to outdir.
    Used to check a frozen (PyInstaller) build, which has no console to print to."""
    app = ChamberApp(settings_file=os.path.join(outdir, "settings.json"))
    try:
        app.update()
        ok = app.recompute_now()
        app.redraw3d()
        app.redraw2d()
        app.update()
        if ok:
            exporters.export_all(app.model, outdir, app.plan)
        return 0 if ok else 1
    finally:
        app.modified = False
        app.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if sys.platform == "win32":
        try:    # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    if len(argv) == 2 and argv[0] == "--selftest":
        os.makedirs(argv[1], exist_ok=True)
        return selftest(argv[1])
    app = ChamberApp()
    if argv:
        app.load_config_file(argv[0])
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
