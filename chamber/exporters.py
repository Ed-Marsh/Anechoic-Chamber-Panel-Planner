"""File output: CSV and summary tables, 2D and 3D DXF, PNG preview.

The command line and the GUI both go through these functions, so a config
produces the same files from either.
"""
import csv
import os

import ezdxf

from chamber.core import (HATFLAT_COLS, BOM_COLS, PANEL_COLS, SURFACES, box_faces,
                          compute_plan, solids)

# Output file names, shared by export_all and the GUI's single-item export.
FILES = {
    "panel_cutlist": "panel_cutlist.csv",
    "hatflat_cutlist": "hatflat_cutlist.csv",
    "bom": "bom.csv",
    "summary": "summary.txt",
    "dxf_2d": "chamber.dxf",
    "dxf_3d": "chamber_3d.dxf",
    "dxf_3d_exploded": "chamber_3d_exploded.dxf",
    "png": "chamber_3d.png",
}


# ---------------------------------------------------------------- tables
def write_panel_cutlist(plan, path):
    with open(path, "w", newline="") as f:
        wr = csv.DictWriter(f, PANEL_COLS)
        wr.writeheader()
        wr.writerows(plan["panel_rows"])
    return path


def write_hatflat_cutlist(plan, path):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(HATFLAT_COLS)
        wr.writerows(plan["hatflat_rows"])
        wr.writerow([])
        wr.writerow(["Stock bars needed (each of hat AND flat)", plan["bar_count"],
                     f"x {plan['stock']} mm"])
        wr.writerow(["Offcut per bar (mm)"] + plan["bar_offcuts"])
    return path


def write_bom(plan, path):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(BOM_COLS)
        wr.writerows(plan["bom"])
        wr.writerow([])
        wr.writerow(["Panel thickness by surface (board + steel both sides, mm)"])
        for row in plan["thickness_rows"]:
            wr.writerow(row)
    return path


def write_summary(plan, path):
    with open(path, "w") as f:
        f.write(plan["summary"])
    return path


# ---------------------------------------------------------------- DXF
def draw(m, outdir, name=FILES["dxf_2d"]):
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    for lname, col in (("PANEL_FULL", 3), ("PANEL_CUT", 1), ("SEAM", 5), ("DOOR", 6),
                       ("CHAMBER", 7), ("TEXT", 2), ("DIM", 4)):
        doc.layers.add(lname, color=col)
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
    path = os.path.join(outdir, name)
    doc.saveas(path)
    return path


def draw3d(m, outdir, explode=0.0, name=FILES["dxf_3d"]):
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


# ---------------------------------------------------------------- PNG
def preview(m, outdir, explode=0.0, name=FILES["png"]):
    """Write the PNG preview; returns None when matplotlib is not installed."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from chamber import render
    except ImportError:
        return None
    # A bare Figure, not pyplot, so this never changes the global matplotlib backend
    # (the GUI has its own Tk canvas open in the same process).
    fig = Figure(figsize=(11, 8))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111, projection="3d")
    render.draw_chamber(ax, m, explode)
    ax.view_init(elev=25, azim=-55)
    path = os.path.join(outdir, name)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    return path


# ---------------------------------------------------------------- everything
def export_all(m, outdir, plan=None):
    """Write every output file into `outdir` (created if needed), exactly as the
    command line does. Returns {"plan": plan, "paths": {key: path-or-None}}."""
    plan = plan or compute_plan(m)
    os.makedirs(outdir, exist_ok=True)
    join = lambda key: os.path.join(outdir, FILES[key])
    write_panel_cutlist(plan, join("panel_cutlist"))
    write_hatflat_cutlist(plan, join("hatflat_cutlist"))
    write_bom(plan, join("bom"))
    write_summary(plan, join("summary"))
    paths = {
        "dxf_2d": draw(m, outdir),
        "dxf_3d": draw3d(m, outdir),
        "dxf_3d_exploded": draw3d(m, outdir, explode=m["cfg"]["explode_mm"],
                                  name=FILES["dxf_3d_exploded"]),
        "png": preview(m, outdir),
    }
    return {"plan": plan, "paths": paths}
