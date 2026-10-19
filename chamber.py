#!/usr/bin/env python3
"""
Anechoic chamber panel planner.

Input : JSON config (all dimensions in millimetres)
Output: chamber.dxf (CAD), bom.csv, panel_cutlist.csv, hatflat_cutlist.csv, summary.txt

Usage : python chamber.py config.json -o out_dir
        python chamber.py --example > config.json

Coordinate system (plan view): x runs west->east along chamber length L,
y runs south->north along chamber width W, z is up.

Surfaces
  floor / ceiling : (L + t_west + t_east) x (W + t_south + t_north)
  north / south   : (L + t_west + t_east) x H   (run full length, E/W walls butt between them)
  east / west     : W x H
Door offset is measured along the wall from the INTERNAL west face (north/south walls)
or INTERNAL south face (east/west walls) to the nearest door edge.
"""
import argparse, csv, json, math, os, sys
import ezdxf

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
    I = cfg["internal"]
    L, W, H = I["length"], I["width"], I["height"]
    base_t = cfg["board_thickness"] + 2 * cfg.get("steel_thickness", 0)
    ov = cfg.get("thickness_override", {})

    def total_t(name):
        if name in ov:
            return ov[name] + 2 * cfg.get("steel_thickness", 0)
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
        if wall not in ("north", "south", "east", "west"):
            raise ValueError("door.wall must be north/south/east/west")
        wl = size[wall][0]
        start = t["west"] if wall in ("north", "south") else 0.0
        u0 = start + dcfg["offset"]
        u1 = u0 + dcfg["width"]
        if u1 > wl or dcfg["height"] > H or dcfg["offset"] < 0:
            raise ValueError("Door does not fit within the wall")
        door = {"wall": wall, "rect": (u0, 0.0, u1, dcfg["height"])}

    surfaces = {}
    for n in SURFACES:
        w, h = size[n]
        d = door["rect"] if door and door["wall"] == n else None
        pieces, seams, xs, ys = tile_surface(w, h, sheet, d, cfg.get("stagger", 0.5))
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


def outputs(m, outdir):
    cfg = m["cfg"]
    kerf = cfg.get("kerf", 3)
    hf = cfg["hat_flat"]
    os.makedirs(outdir, exist_ok=True)

    panel_rows, cut_items, full_count = [], [], 0
    for n in SURFACES:
        s = m["surfaces"][n]
        k = 0
        for (x0, y0, x1, y1), full in s["pieces"]:
            k += 1
            pid = f"{n[0].upper()}{n[1] if n in ('north','south') else ''}-{k:02d}".replace("N", "N").replace("S", "S")
            pid = f"{n[:3].upper()}-{k:02d}"
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

    with open(os.path.join(outdir, "panel_cutlist.csv"), "w", newline="") as f:
        cols = ["id", "surface", "type", "width", "height", "board_mm", "x0", "y0",
                "from_sheet", "sheet_x", "sheet_y", "rotated"]
        wr = csv.DictWriter(f, cols)
        wr.writeheader()
        wr.writerows(panel_rows)

    # ---- hat & flat
    seams = []
    for n in SURFACES:
        for k, (o, pos, a, b) in enumerate(m["surfaces"][n]["seams"], 1):
            seams.append((f"{n[:3].upper()}-J{k:02d}", n, b - a))
    if cfg.get("corner_joints"):
        t = m["t"]
        Lf = m["surfaces"]["floor"]["w"]; Wf = m["surfaces"]["floor"]["h"]
        for lab, ln in (("FLR-EDGE-N", Lf), ("FLR-EDGE-S", Lf), ("FLR-EDGE-E", Wf), ("FLR-EDGE-W", Wf),
                        ("CLG-EDGE-N", Lf), ("CLG-EDGE-S", Lf), ("CLG-EDGE-E", Wf), ("CLG-EDGE-W", Wf)):
            seams.append((lab, "corner", ln))
        for lab in ("VERT-NE", "VERT-NW", "VERT-SE", "VERT-SW"):
            seams.append((lab, "corner", m["H"]))

    stock = hf["stock_length"]
    clr = hf.get("end_clearance", 0)
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
                b["cuts"].append((lab, ln)); b["left"] -= ln + kerf
                break
        else:
            bars.append(dict(left=stock - ln - kerf, cuts=[(lab, ln)]))
    bar_of = {}
    for i, b in enumerate(bars, 1):
        for lab, ln in b["cuts"]:
            bar_of[lab] = i
    total_hf = sum(p[2] for p in pieces)
    with open(os.path.join(outdir, "hatflat_cutlist.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["joint", "surface", "cut_length_mm", "qty_hat", "qty_flat", "from_stock_bar"])
        for lab, surf, ln in pieces:
            wr.writerow([lab, surf, round(ln, 1), 1, 1, bar_of[lab]])
        wr.writerow([])
        wr.writerow(["Stock bars needed (each of hat AND flat)", len(bars), f"x {stock} mm"])
        wr.writerow(["Offcut per bar (mm)"] + [round(b["left"], 0) for b in bars])

    # ---- BOM
    total_sheets = len(sheets) + full_count
    screws = math.ceil(total_hf / hf["screw_pitch"]) * 4 if hf.get("screw_pitch") else 0
    sx, sy = m["sheet"]
    bom = [
        ("Hardboard panel, steel-clad both faces", f"{sx} x {sy} mm", "per surface thickness", total_sheets, "sheets"),
        ("  - used whole (full panels)", "", "", full_count, "sheets"),
        ("  - used for cut pieces", "", "", len(sheets), "sheets"),
        ("Hat section", f"{hf['hat_width']} wide x {hf['hat_depth']} deep", f"{stock} mm stock", len(bars), "bars"),
        ("Flat section", f"{hf['flat_width']} wide", f"{stock} mm stock", len(bars), "bars"),
        ("Hat + flat total run (each)", "", "", round(total_hf / 1000, 2), "m"),
        ("Fasteners (est. 4 per pitch interval: 2 hat, 2 flat)", f"pitch {hf.get('screw_pitch', 0)} mm", "", screws, "pcs"),
    ]
    with open(os.path.join(outdir, "bom.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["item", "size", "notes", "qty", "unit"])
        wr.writerows(bom)
        wr.writerow([])
        wr.writerow(["Panel thickness by surface (board + steel both sides, mm)"])
        for n in SURFACES:
            wr.writerow([n, m["board_t"][n], round(m["t"][n], 2)])

    # ---- summary
    ext = (m["L"] + m["t"]["west"] + m["t"]["east"], m["W"] + m["t"]["south"] + m["t"]["north"],
           m["H"] + m["t"]["floor"] + m["t"]["ceiling"])
    lines = [f"Internal : {m['L']} x {m['W']} x {m['H']} mm",
             f"External : {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm",
             f"Door     : {m['door']['wall']} wall, {cfg['door']['width']} x {cfg['door']['height']}, offset {cfg['door']['offset']}" if m["door"] else "Door     : none",
             f"Panels   : {full_count} full + {len(cut_items)} cut pieces from {len(sheets)} sheets = {total_sheets} sheets",
             f"Hat/flat : {total_hf/1000:.2f} m each, {len(bars)} x {stock} mm bars each"]
    open(os.path.join(outdir, "summary.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return panel_rows, seams


# ---------------------------------------------------------------- DXF
def draw(m, outdir):
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    for name, col in (("PANEL_FULL", 3), ("PANEL_CUT", 1), ("SEAM", 5), ("DOOR", 6),
                      ("CHAMBER", 7), ("TEXT", 2), ("DIM", 4)):
        doc.layers.add(name, color=col)
    t, L, W, H = m["t"], m["L"], m["W"], m["H"]
    ex0, ey0 = -t["west"], -t["south"]
    ex1, ey1 = L + t["east"], W + t["north"]
    th = max(40.0, H / 60)

    def rect(x0, y0, x1, y1, layer):
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                           dxfattribs={"layer": layer})

    def text(s, x, y, h=th, layer="TEXT"):
        msp.add_text(s, height=h, dxfattribs={"layer": layer}).set_placement((x, y))

    # ---- plan view (origin) with wall thicknesses
    rect(ex0, ey0, ex1, ey1, "CHAMBER")
    rect(0, 0, L, W, "CHAMBER")
    text(f"PLAN  internal {L} x {W} x {H}", ex0, ey1 + 3 * th)
    d = m["door"]
    if d:
        u0, _, u1, _ = d["rect"]
        w = d["wall"]
        if w == "south":
            msp.add_line((u0 - t["west"], ey0), (u0 - t["west"], 0), dxfattribs={"layer": "DOOR"})
            msp.add_line((u1 - t["west"], ey0), (u1 - t["west"], 0), dxfattribs={"layer": "DOOR"})
        elif w == "north":
            msp.add_line((u0 - t["west"], W), (u0 - t["west"], ey1), dxfattribs={"layer": "DOOR"})
            msp.add_line((u1 - t["west"], W), (u1 - t["west"], ey1), dxfattribs={"layer": "DOOR"})
        elif w == "west":
            msp.add_line((ex0, u0), (0, u0), dxfattribs={"layer": "DOOR"})
            msp.add_line((ex0, u1), (0, u1), dxfattribs={"layer": "DOOR"})
        else:
            msp.add_line((L, u0), (ex1, u0), dxfattribs={"layer": "DOOR"})
            msp.add_line((L, u1), (ex1, u1), dxfattribs={"layer": "DOOR"})
        text("DOOR", (u0 - t["west"] if w in ("north", "south") else ex0), (ey0 - 2 * th if w == "south" else ey1 + th))

    # ---- surface layouts below the plan
    cur_y = ey0 - 6 * th - 1000
    gap = 800
    for n in SURFACES:
        s = m["surfaces"][n]
        ox, oy = 0.0, cur_y - s["h"]
        text(f"{n.upper()}  {s['w']:.0f} x {s['h']:.0f} (board {m['board_t'][n]} mm)", ox, oy + s["h"] + th)
        k = 0
        for (x0, y0, x1, y1), full in s["pieces"]:
            k += 1
            rect(ox + x0, oy + y0, ox + x1, oy + y1, "PANEL_FULL" if full else "PANEL_CUT")
            text(f"{n[:3].upper()}-{k:02d}", ox + x0 + th / 2, oy + y0 + th / 2, th * 0.8)
            if not full:
                text(f"{x1-x0:.0f}x{y1-y0:.0f}", ox + x0 + th / 2, oy + y0 + 2 * th, th * 0.7)
        for o, pos, a, b in s["seams"]:
            if o == "V":
                msp.add_line((ox + pos, oy + a), (ox + pos, oy + b), dxfattribs={"layer": "SEAM"})
            else:
                msp.add_line((ox + a, oy + pos), (ox + b, oy + pos), dxfattribs={"layer": "SEAM"})
        if s["door"]:
            rect(ox + s["door"][0], oy + s["door"][1], ox + s["door"][2], oy + s["door"][3], "DOOR")
            text(f"DOOR {s['door'][2]-s['door'][0]:.0f} x {s['door'][3]:.0f}",
                 ox + s["door"][0] + th, oy + s["door"][3] / 2)
        cur_y = oy - gap
    path = os.path.join(outdir, "chamber.dxf")
    doc.saveas(path)
    return path


# ---------------------------------------------------------------- 3D
def solids(m, explode=0.0):
    """Return list of (layer, label, (x0,y0,z0,x1,y1,z1)) boxes in chamber coordinates (mm).
    explode pushes each surface outward by that many mm (0 = assembled)."""
    t, L, W, H = m["t"], m["L"], m["W"], m["H"]
    cfg = m["cfg"]
    hf = cfg["hat_flat"]
    hw, hd, fw = hf["hat_width"], hf["hat_depth"], hf["flat_width"]
    ft = hf.get("flat_thickness", 3)
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
            out.append((f"PANEL_{n.upper()}", f"{n[:3].upper()}-{k:02d}",
                        (b[0] + sx, b[1] + sy, b[2] + sz, b[3] + sx, b[4] + sy, b[5] + sz)))
        if hf.get("draw_in_3d", True):
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


def draw3d(m, outdir, explode=0.0, name="chamber_3d.dxf"):
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    cols = {"FLOOR": 3, "CEILING": 4, "NORTH": 5, "SOUTH": 6, "EAST": 2, "WEST": 1}
    for n, c in cols.items():
        doc.layers.add(f"PANEL_{n}", color=c)
    doc.layers.add("HAT", color=30)
    doc.layers.add("FLAT", color=8)
    for layer, label, b in solids(m, explode):
        pf = msp.add_polyface(dxfattribs={"layer": layer})
        pf.append_faces(box_faces(b))
        pf.optimize()
    path = os.path.join(outdir, name)
    doc.saveas(path)
    return path


def preview(m, outdir, explode=0.0, name="chamber_3d.png"):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    except ImportError:
        return None
    fig = plt.figure(figsize=(11, 8))
    ax = fig.add_subplot(111, projection="3d")
    colour = {"HAT": "#c97b1a", "FLAT": "#777777"}
    pal = {"FLOOR": "#7fb069", "CEILING": "#8ecae6", "NORTH": "#9d8df1", "SOUTH": "#f4a261",
           "EAST": "#e9c46a", "WEST": "#e76f51"}
    for layer, label, b in solids(m, explode):
        c = colour.get(layer) or pal[layer.split("_")[1]]
        alpha = 0.9 if layer in colour else 0.35
        ax.add_collection3d(Poly3DCollection(box_faces(b), facecolor=c, edgecolor="k",
                                             linewidth=0.3, alpha=alpha))
    ext = (m["L"], m["W"], m["H"])
    ax.set_xlim(0, ext[0]); ax.set_ylim(0, ext[1]); ax.set_zlim(0, ext[2])
    ax.set_box_aspect(ext)
    ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)"); ax.set_zlabel("z (mm)")
    ax.view_init(elev=25, azim=-55)
    path = os.path.join(outdir, name)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?")
    ap.add_argument("-o", "--out", default="out")
    ap.add_argument("--example", action="store_true", help="print example config")
    a = ap.parse_args()
    if a.example or not a.config:
        print(json.dumps(EXAMPLE, indent=2))
        return
    cfg = json.load(open(a.config))
    m = build(cfg)
    os.makedirs(a.out, exist_ok=True)
    outputs(m, a.out)
    print("DXF:", draw(m, a.out))
    print("3D DXF:", draw3d(m, a.out))
    ex = cfg.get("explode_mm", 300)
    print("3D DXF (exploded):", draw3d(m, a.out, explode=ex, name="chamber_3d_exploded.dxf"))
    print("Preview:", preview(m, a.out))


if __name__ == "__main__":
    main()
