"""Chamber model: config defaults and validation, panel tiling, cut-list packing
and 3D solids.

Nothing in here prints or touches the file system, so the command line and the
GUI can share it. Dimensions are in millimetres.

Coordinate system (plan view): x runs west->east along chamber length L,
y runs south->north along chamber width W, z is up.

Surfaces
  floor / ceiling : (L + t_west + t_east) x (W + t_south + t_north)
  north / south   : (L + t_west + t_east) x H   (run full length, E/W walls butt between them)
  east / west     : W x H
Door offset is measured along the wall from the INTERNAL west face (north/south walls)
or INTERNAL south face (east/west walls) to the nearest door edge.
"""
import copy
import math

EXAMPLE = {
    "internal": {"length": 4000, "width": 3000, "height": 2400},
    "sheet": {"length": 2440, "width": 1220},
    "board_thickness": 22,
    "steel_thickness": 0.7,
    "thickness_override": {"ceiling": 12},
    "hat_flat": {
        "hat_width": 50, "hat_depth": 25, "flat_width": 50,
        "stock_length": 3000, "end_clearance": 0, "screw_pitch": 150
    },
    "corner_joints": False,
    "stagger": 0.5,
    "kerf": 3,
    "door": {"wall": "south", "offset": 1000, "width": 900, "height": 2000}
}

SURFACES = ["floor", "ceiling", "north", "south", "east", "west"]
WALLS = ["north", "south", "east", "west"]

# Values used when an optional key is missing. Required geometry (internal, sheet,
# board_thickness) falls back to the example so a partial file still opens.
DEFAULTS = {
    "internal": EXAMPLE["internal"],
    "sheet": EXAMPLE["sheet"],
    "board_thickness": EXAMPLE["board_thickness"],
    "steel_thickness": 0,
    "thickness_override": {},
    "hat_flat": {
        "hat_width": 50, "hat_depth": 25, "flat_width": 50, "flat_thickness": 3,
        "stock_length": 3000, "end_clearance": 0, "screw_pitch": 0, "draw_in_3d": True,
    },
    "corner_joints": False,
    "stagger": 0.5,
    "kerf": 3,
    "explode_mm": 300,
}

# Refuse layouts that would need an absurd number of sheets (tiny sheet size typed
# into a form) rather than hanging while tiling them.
MAX_SHEETS_ESTIMATE = 20000


class ConfigError(ValueError):
    """Invalid configuration. `issues` is a list of (field_path, message); the
    path is dotted ("door.offset") or "" when the problem is not tied to one field."""

    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__("; ".join(msg for _, msg in self.issues))


# ---------------------------------------------------------------- config
def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def normalise_config(raw):
    """Deep copy of `raw` with defaults filled in. Unknown keys are kept."""
    if not isinstance(raw, dict):
        raise ConfigError([("", "The configuration must be a JSON object")])
    cfg = copy.deepcopy(raw)
    for key, default in DEFAULTS.items():
        if cfg.get(key) is None:
            cfg[key] = copy.deepcopy(default)
        elif isinstance(default, dict) and isinstance(cfg[key], dict):
            for k, v in default.items():
                cfg[key].setdefault(k, copy.deepcopy(v))
    return cfg


def validate_config(raw):
    """Return (normalised_cfg, issues). `issues` is a list of (field_path, message)
    in plain English; it is empty when the config is usable."""
    cfg = normalise_config(raw)
    issues = []

    def section(key):
        if not isinstance(cfg[key], dict):
            issues.append((key, "Must be an object"))
            return {}
        return cfg[key]

    def number(path, value, minimum=None, strict=False, label=None):
        label = label or path.split(".")[-1].replace("_", " ").capitalize()
        if not _is_num(value):
            issues.append((path, f"{label} must be a number"))
        elif minimum is not None and (value <= minimum if strict else value < minimum):
            word = "greater than" if strict else "at least"
            issues.append((path, f"{label} must be {word} {minimum:g}"))

    for key in ("internal", "sheet", "hat_flat"):
        sec = section(key)
        for k, default in DEFAULTS[key].items():
            if key == "hat_flat" and k == "draw_in_3d":
                continue
            if key == "hat_flat" and k in ("end_clearance", "screw_pitch"):
                number(f"{key}.{k}", sec.get(k), 0)
            else:
                number(f"{key}.{k}", sec.get(k), 0, strict=True)
    number("board_thickness", cfg["board_thickness"], 0, strict=True)
    number("steel_thickness", cfg["steel_thickness"], 0)
    number("stagger", cfg["stagger"], 0)
    number("kerf", cfg["kerf"], 0)
    number("explode_mm", cfg["explode_mm"], 0)

    ov = section("thickness_override")
    for k, v in ov.items():
        if k not in SURFACES:
            issues.append((f"thickness_override.{k}",
                           f"Unknown surface '{k}' (use {', '.join(SURFACES)})"))
        else:
            number(f"thickness_override.{k}", v, 0, strict=True, label=f"{k.capitalize()} thickness")

    dcfg = cfg.get("door")
    if dcfg:
        if not isinstance(dcfg, dict):
            issues.append(("door", "Door must be an object"))
        else:
            if dcfg.get("wall") not in WALLS:
                issues.append(("door.wall", "Door wall must be north, south, east or west"))
            dcfg.setdefault("offset", 0)
            number("door.offset", dcfg["offset"], 0)
            number("door.width", dcfg.get("width"), 0, strict=True)
            number("door.height", dcfg.get("height"), 0, strict=True)

    if issues:
        return cfg, issues

    # Cross-field checks need the numbers to be sane first.
    I, S = cfg["internal"], cfg["sheet"]
    base_t = cfg["board_thickness"] + 2 * cfg["steel_thickness"]
    t = {n: ov.get(n, cfg["board_thickness"]) + 2 * cfg["steel_thickness"] for n in SURFACES}
    L, W, H = I["length"], I["width"], I["height"]
    sheet_area = S["length"] * S["width"]
    total_area = 2 * (L + 2 * base_t) * (W + 2 * base_t) + 2 * (L + 2 * base_t) * H + 2 * W * H
    if total_area / sheet_area > MAX_SHEETS_ESTIMATE:
        issues.append(("sheet.length", "The sheet size is too small for this chamber "
                                       "(it would need an unreasonable number of sheets)"))
    if dcfg:
        wall = dcfg["wall"]
        wl = (L + t["west"] + t["east"]) if wall in ("north", "south") else W
        start = t["west"] if wall in ("north", "south") else 0.0
        if start + dcfg["offset"] + dcfg["width"] > wl:
            issues.append(("door.width", "Door does not fit within the wall "
                                        f"(the wall is {wl:g} mm long, the door ends at "
                                        f"{start + dcfg['offset'] + dcfg['width']:g} mm)"))
        if dcfg["height"] > H:
            issues.append(("door.height", f"Door does not fit within the wall "
                                          f"(the wall is {H:g} mm high)"))
    return cfg, issues


def check_config(raw):
    """Normalise and validate; return the normalised config or raise ConfigError."""
    cfg, issues = validate_config(raw)
    if issues:
        raise ConfigError(issues)
    return cfg


# ---------------------------------------------------------------- geometry
def subtract(rect, door):
    """rect, door = (x0,y0,x1,y1). Return list of rects of rect minus door."""
    x0, y0, x1, y1 = rect
    dx0, dy0, dx1, dy1 = door
    ix0, iy0, ix1, iy1 = max(x0, dx0), max(y0, dy0), min(x1, dx1), min(y1, dy1)
    if ix0 >= ix1 or iy0 >= iy1:
        return [rect]
    out = [(x0, y0, x1, iy0),          # below
           (x0, iy1, x1, y1),          # above
           (x0, iy0, ix0, iy1),        # left
           (ix1, iy0, x1, iy1)]        # right
    return [r for r in out if r[2] - r[0] > 0.01 and r[3] - r[1] > 0.01]


def grid_lines(total, step):
    pts, p = [0.0], step
    while p < total - 0.01:
        pts.append(p)
        p += step
    pts.append(float(total))
    return pts


def row_lines(w, step, offset):
    """Joint positions along a row of length w: first piece 'offset' long (if >0),
    then full sheets of length 'step', remainder last."""
    pts, p = [0.0], offset if offset > 0.01 else step
    while p < w - 0.01:
        pts.append(p)
        p += step
    pts.append(float(w))
    return pts


def tile_surface(w, h, sheet, door=None, stagger=0.5):
    """Tile a w x h surface with sheets in running bond: alternate rows are shifted
    by stagger * sheet-length (0 = straight grid). Tries both sheet orientations,
    keeps whichever gives fewer pieces then less seam length."""
    best = None
    a, b = max(sheet), min(sheet)
    for sx, sy in ((a, b), (b, a)):
        ys = grid_lines(h, sy)
        pieces, seams, xs_first = [], [], None
        for j in range(len(ys) - 1):
            y0, y1 = ys[j], ys[j + 1]
            off = (stagger * sx) % sx if j % 2 else 0.0
            xs = row_lines(w, sx, off)
            if xs_first is None:
                xs_first = xs
            for i in range(len(xs) - 1):
                r = (xs[i], y0, xs[i + 1], y1)
                parts = subtract(r, door) if door else [r]
                for p in parts:
                    full = (abs((p[2] - p[0]) - sx) < 0.01 and abs((p[3] - p[1]) - sy) < 0.01)
                    pieces.append((p, full))
            for x in xs[1:-1]:   # cross joints only span this one row
                for s, e in clip_line(y0, y1, door, vertical=True, pos=x):
                    seams.append(("V", x, s, e))
        for y in ys[1:-1]:       # joints between rows run the full width
            for s, e in clip_line(0, w, door, vertical=False, pos=y):
                seams.append(("H", y, s, e))
        seam_len = sum(e - s for _, _, s, e in seams)
        key = (len(pieces), seam_len)
        if best is None or key < best[0]:
            best = (key, pieces, seams, xs_first, ys)
    return best[1], best[2], best[3], best[4]


def clip_line(lo, hi, door, vertical, pos):
    """Seam line from lo..hi at pos; remove portion passing through door opening."""
    if not door:
        return [(lo, hi)]
    dx0, dy0, dx1, dy1 = door
    if vertical:
        across0, across1, along0, along1 = dx0, dx1, dy0, dy1
    else:
        across0, across1, along0, along1 = dy0, dy1, dx0, dx1
    if not (across0 < pos < across1):
        return [(lo, hi)]
    segs = []
    if along0 > lo:
        segs.append((lo, min(along0, hi)))
    if along1 < hi:
        segs.append((max(along1, lo), hi))
    return [s for s in segs if s[1] - s[0] > 0.01]


# ---------------------------------------------------------------- model
def build(cfg):
    """Build the chamber model from a config dict. Missing optional keys take their
    defaults; a bad config raises ConfigError with plain-English messages."""
    cfg = check_config(cfg)
    I = cfg["internal"]
    L, W, H = I["length"], I["width"], I["height"]
    base_t = cfg["board_thickness"] + 2 * cfg["steel_thickness"]
    ov = cfg["thickness_override"]

    def total_t(name):
        if name in ov:
            return ov[name] + 2 * cfg["steel_thickness"]
        return base_t

    t = {n: total_t(n) for n in SURFACES}
    board_t = {n: ov.get(n, cfg["board_thickness"]) for n in SURFACES}
    sheet = (cfg["sheet"]["length"], cfg["sheet"]["width"])

    size = {
        "floor": (L + t["west"] + t["east"], W + t["south"] + t["north"]),
        "ceiling": (L + t["west"] + t["east"], W + t["south"] + t["north"]),
        "north": (L + t["west"] + t["east"], H),
        "south": (L + t["west"] + t["east"], H),
        "east": (W, H),
        "west": (W, H),
    }

    door = None
    dcfg = cfg.get("door")
    if dcfg:
        wall = dcfg["wall"]
        wl = size[wall][0]
        start = t["west"] if wall in ("north", "south") else 0.0
        u0 = start + dcfg["offset"]
        u1 = u0 + dcfg["width"]
        door = {"wall": wall, "rect": (u0, 0.0, u1, dcfg["height"])}

    surfaces = {}
    for n in SURFACES:
        w, h = size[n]
        d = door["rect"] if door and door["wall"] == n else None
        pieces, seams, xs, ys = tile_surface(w, h, sheet, d, cfg["stagger"])
        surfaces[n] = dict(w=w, h=h, pieces=pieces, seams=seams, door=d, xs=xs, ys=ys)

    return dict(cfg=cfg, L=L, W=W, H=H, t=t, board_t=board_t, sheet=sheet,
                surfaces=surfaces, door=door)


# ---------------------------------------------------------------- cut lists
def pack_offcuts(cut_pieces, sheet, kerf):
    """Shelf packing of (id, w, h) onto sheets; returns list of sheets with placements."""
    sw, sh = max(sheet), min(sheet)
    items = sorted(cut_pieces, key=lambda p: -max(p[1], p[2]))
    sheets = []  # each: dict(shelves=[{y,h,x}], used_h, placements=[])
    for pid, w, h in items:
        placed = False
        for s in sheets:
            if place(s, pid, w, h, sw, sh, kerf):
                placed = True
                break
        if not placed:
            s = dict(shelves=[], used=0.0, placements=[])
            if not place(s, pid, w, h, sw, sh, kerf):
                raise ValueError(f"Piece {pid} ({w:.0f}x{h:.0f}) does not fit on a sheet")
            sheets.append(s)
    return sheets


def place(s, pid, w, h, sw, sh, kerf):
    for (pw, ph, rot) in ((w, h, False), (h, w, True)):
        pw_k, ph_k = pw + kerf, ph + kerf
        if pw_k > sw + kerf or ph_k > sh + kerf:
            continue
        for shelf in s["shelves"]:
            if ph_k <= shelf["h"] + 0.01 and shelf["x"] + pw_k <= sw + kerf + 0.01:
                s["placements"].append((pid, pw, ph, shelf["x"], shelf["y"], rot))
                shelf["x"] += pw_k
                return True
        if s["used"] + ph_k <= sh + kerf + 0.01:
            s["shelves"].append(dict(y=s["used"], h=ph_k, x=pw_k))
            s["placements"].append((pid, pw, ph, 0.0, s["used"], rot))
            s["used"] += ph_k
            return True
    return False


PANEL_COLS = ["id", "surface", "type", "width", "height", "board_mm", "x0", "y0",
              "from_sheet", "sheet_x", "sheet_y", "rotated"]
HATFLAT_COLS = ["joint", "surface", "cut_length_mm", "qty_hat", "qty_flat", "from_stock_bar"]
BOM_COLS = ["item", "size", "notes", "qty", "unit"]


def panel_id(surface, k):
    return f"{surface[:3].upper()}-{k:02d}"


def compute_plan(m):
    """Cut lists, bill of materials and summary text for a built model. Pure data:
    the exporters turn it into files and the GUI into tables."""
    cfg = m["cfg"]
    kerf = cfg["kerf"]
    hf = cfg["hat_flat"]

    panel_rows, cut_items, full_count = [], [], 0
    for n in SURFACES:
        s = m["surfaces"][n]
        for k, ((x0, y0, x1, y1), full) in enumerate(s["pieces"], 1):
            pid = panel_id(n, k)
            w, h = x1 - x0, y1 - y0
            panel_rows.append(dict(id=pid, surface=n, type="FULL" if full else "CUT",
                                   width=round(w, 1), height=round(h, 1),
                                   board_mm=m["board_t"][n], x0=round(x0, 1), y0=round(y0, 1)))
            if full:
                full_count += 1
            else:
                cut_items.append((pid, w, h))
    # which sheet does each cut piece come from
    sheets = pack_offcuts(cut_items, m["sheet"], kerf)
    sheet_of = {}
    for i, sh in enumerate(sheets, 1):
        for pid, w, h, x, y, rot in sh["placements"]:
            sheet_of[pid] = (i, round(x, 1), round(y, 1), rot)
    for r in panel_rows:
        if r["type"] == "CUT":
            i, x, y, rot = sheet_of[r["id"]]
            r.update(from_sheet=i, sheet_x=x, sheet_y=y, rotated="Y" if rot else "")
        else:
            r.update(from_sheet="", sheet_x="", sheet_y="", rotated="")

    # ---- hat & flat
    seams = []
    for n in SURFACES:
        for k, (o, pos, a, b) in enumerate(m["surfaces"][n]["seams"], 1):
            seams.append((f"{n[:3].upper()}-J{k:02d}", n, b - a))
    if cfg["corner_joints"]:
        Lf = m["surfaces"]["floor"]["w"]
        Wf = m["surfaces"]["floor"]["h"]
        for lab, ln in (("FLR-EDGE-N", Lf), ("FLR-EDGE-S", Lf), ("FLR-EDGE-E", Wf), ("FLR-EDGE-W", Wf),
                        ("CLG-EDGE-N", Lf), ("CLG-EDGE-S", Lf), ("CLG-EDGE-E", Wf), ("CLG-EDGE-W", Wf)):
            seams.append((lab, "corner", ln))
        for lab in ("VERT-NE", "VERT-NW", "VERT-SE", "VERT-SW"):
            seams.append((lab, "corner", m["H"]))

    stock = hf["stock_length"]
    clr = hf["end_clearance"]
    pieces = []  # (label, surface, length)
    for lab, surf, ln in seams:
        ln = ln - 2 * clr
        parts = max(1, math.ceil(ln / stock - 1e-9))
        each = ln / parts
        for p in range(parts):
            pieces.append((lab + (f"/{p+1}" if parts > 1 else ""), surf, each))
    bars = []  # first-fit decreasing, per type
    for lab, surf, ln in sorted(pieces, key=lambda p: -p[2]):
        for b in bars:
            if b["left"] >= ln + kerf - 0.01:
                b["cuts"].append((lab, ln))
                b["left"] -= ln + kerf
                break
        else:
            bars.append(dict(left=stock - ln - kerf, cuts=[(lab, ln)]))
    bar_of = {}
    for i, b in enumerate(bars, 1):
        for lab, ln in b["cuts"]:
            bar_of[lab] = i
    total_hf = sum(p[2] for p in pieces)
    hatflat_rows = [[lab, surf, round(ln, 1), 1, 1, bar_of[lab]] for lab, surf, ln in pieces]
    bar_offcuts = [round(b["left"], 0) for b in bars]

    # ---- BOM
    total_sheets = len(sheets) + full_count
    screws = math.ceil(total_hf / hf["screw_pitch"]) * 4 if hf["screw_pitch"] else 0
    sx, sy = m["sheet"]
    bom = [
        ("Hardboard panel, steel-clad both faces", f"{sx} x {sy} mm", "per surface thickness", total_sheets, "sheets"),
        ("  - used whole (full panels)", "", "", full_count, "sheets"),
        ("  - used for cut pieces", "", "", len(sheets), "sheets"),
        ("Hat section", f"{hf['hat_width']} wide x {hf['hat_depth']} deep", f"{stock} mm stock", len(bars), "bars"),
        ("Flat section", f"{hf['flat_width']} wide", f"{stock} mm stock", len(bars), "bars"),
        ("Hat + flat total run (each)", "", "", round(total_hf / 1000, 2), "m"),
        ("Fasteners (est. 4 per pitch interval: 2 hat, 2 flat)", f"pitch {hf['screw_pitch']} mm", "", screws, "pcs"),
    ]
    thickness_rows = [(n, m["board_t"][n], round(m["t"][n], 2)) for n in SURFACES]

    # ---- summary
    ext = (m["L"] + m["t"]["west"] + m["t"]["east"], m["W"] + m["t"]["south"] + m["t"]["north"],
           m["H"] + m["t"]["floor"] + m["t"]["ceiling"])
    d = cfg.get("door")
    lines = [f"Internal : {m['L']} x {m['W']} x {m['H']} mm",
             f"External : {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm",
             f"Door     : {m['door']['wall']} wall, {d['width']} x {d['height']}, offset {d['offset']}" if m["door"] else "Door     : none",
             f"Panels   : {full_count} full + {len(cut_items)} cut pieces from {len(sheets)} sheets = {total_sheets} sheets",
             f"Hat/flat : {total_hf/1000:.2f} m each, {len(bars)} x {stock} mm bars each"]

    return dict(
        panel_rows=panel_rows, hatflat_rows=hatflat_rows, bom=bom,
        thickness_rows=thickness_rows, seams=seams, sheets=sheets, bars=bars,
        bar_count=len(bars), bar_offcuts=bar_offcuts, stock=stock,
        full_count=full_count, cut_count=len(cut_items), sheets_for_cuts=len(sheets),
        total_sheets=total_sheets, total_hf=total_hf, fasteners=screws, external=ext,
        summary_lines=lines, summary="\n".join(lines) + "\n")


# ---------------------------------------------------------------- 3D
def solids(m, explode=0.0):
    """Return list of (layer, label, (x0,y0,z0,x1,y1,z1)) boxes in chamber coordinates (mm).
    explode pushes each surface outward by that many mm (0 = assembled)."""
    t, L, W, H = m["t"], m["L"], m["W"], m["H"]
    cfg = m["cfg"]
    hf = cfg["hat_flat"]
    hw, hd, fw = hf["hat_width"], hf["hat_depth"], hf["flat_width"]
    ft = hf["flat_thickness"]
    out = []

    def to3d(n, u0, v0, u1, v1, d0, d1):
        """Map surface-local rect (u,v) and depth range d0..d1 (distance from INTERNAL
        face, outward positive) to a world box."""
        if n == "floor":
            return (-t["west"] + u0, -t["south"] + v0, -d1, -t["west"] + u1, -t["south"] + v1, -d0)
        if n == "ceiling":
            return (-t["west"] + u0, -t["south"] + v0, H + d0, -t["west"] + u1, -t["south"] + v1, H + d1)
        if n == "north":
            return (-t["west"] + u0, W + d0, v0, -t["west"] + u1, W + d1, v1)
        if n == "south":
            return (-t["west"] + u0, -d1, v0, -t["west"] + u1, -d0, v1)
        if n == "east":
            return (L + d0, u0, v0, L + d1, u1, v1)
        return (-d1, u0, v0, -d0, u1, v1)  # west

    shift = {"floor": (0, 0, -1), "ceiling": (0, 0, 1), "north": (0, 1, 0),
             "south": (0, -1, 0), "east": (1, 0, 0), "west": (-1, 0, 0)}
    for n in SURFACES:
        s = m["surfaces"][n]
        tn = m["t"][n]
        sx, sy, sz = (c * explode for c in shift[n])
        k = 0
        for (x0, y0, x1, y1), full in s["pieces"]:
            k += 1
            b = to3d(n, x0, y0, x1, y1, 0, tn)
            out.append((f"PANEL_{n.upper()}", panel_id(n, k),
                        (b[0] + sx, b[1] + sy, b[2] + sz, b[3] + sx, b[4] + sy, b[5] + sz)))
        if hf["draw_in_3d"]:
            for o, pos, a, b_ in s["seams"]:
                if o == "V":
                    hat = (pos - hw / 2, a, tn, pos + hw / 2, b_, tn + hd)
                    flat = (pos - fw / 2, a, -ft, pos + fw / 2, b_, 0)
                else:
                    hat = (a, pos - hw / 2, tn, b_, pos + hw / 2, tn + hd)
                    flat = (a, pos - fw / 2, -ft, b_, pos + fw / 2, 0)
                for layer, r in (("HAT", hat), ("FLAT", flat)):
                    bx = to3d(n, r[0], r[1], r[3], r[4], r[2], r[5])
                    out.append((layer, n, (bx[0] + sx, bx[1] + sy, bx[2] + sz,
                                           bx[3] + sx, bx[4] + sy, bx[5] + sz)))
    return out


def box_faces(b):
    x0, y0, z0, x1, y1, z1 = b
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    idx = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    return [[v[i] for i in f] for f in idx]
