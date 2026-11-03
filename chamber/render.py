"""matplotlib drawing shared by the PNG preview and the GUI. Needs matplotlib."""
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from chamber.core import box_faces, panel_id, solids

HATFLAT_COLOURS = {"HAT": "#c97b1a", "FLAT": "#777777"}
SURFACE_COLOURS = {"FLOOR": "#7fb069", "CEILING": "#8ecae6", "NORTH": "#9d8df1",
                   "SOUTH": "#f4a261", "EAST": "#e9c46a", "WEST": "#e76f51"}


def surface_of(layer, label):
    """Surface name a solid belongs to (hat/flat solids carry it as their label)."""
    return layer.split("_")[1].lower() if layer.startswith("PANEL_") else label


def draw_chamber(ax, m, explode=0.0, hidden=(), show_hatflat=True, merged=False, margin=None, zoom=1):
    """Draw the chamber's boxes on a 3D axes.

    hidden        surface names to leave out (their hat & flat go too)
    show_hatflat  False hides all hat & flat
    merged        one collection per layer instead of one per box: far quicker to
                  rotate, used by the GUI. The PNG preview keeps per-box drawing.
    margin        None keeps the preview's limits (the internal volume); a number
                  in mm frames the whole external shell, explosion included.
    zoom          magnification of the box (1 = fit)
    """
    shown = [(layer, b) for layer, label, b in solids(m, explode)
             if surface_of(layer, label) not in hidden
             and (show_hatflat or layer not in HATFLAT_COLOURS)]

    def style(layer):
        c = HATFLAT_COLOURS.get(layer) or SURFACE_COLOURS[layer.split("_")[1]]
        return c, 0.9 if layer in HATFLAT_COLOURS else 0.35

    if merged:
        groups = {}
        for layer, b in shown:
            groups.setdefault(layer, []).extend(box_faces(b))
        for layer, faces in groups.items():
            c, alpha = style(layer)
            coll = Poly3DCollection(faces, facecolor=c, edgecolor="k", linewidth=0.3, alpha=alpha)
            # 3D axes keep a square drawing area; zoomed in, the chamber is bigger than it
            # and would be cut off to that square while the axes and panes carry on.
            coll.set_clip_on(False)
            ax.add_collection3d(coll)
    else:
        for layer, b in shown:   # solids() order, as the original preview drew it
            c, alpha = style(layer)
            ax.add_collection3d(Poly3DCollection(box_faces(b), facecolor=c, edgecolor="k",
                                                 linewidth=0.3, alpha=alpha))
    ext = (m["L"], m["W"], m["H"])
    if margin is None:
        lo, hi = (0, 0, 0), ext
        aspect = ext
    else:
        t = m["t"]
        lo = (-t["west"] - explode - margin, -t["south"] - explode - margin,
              -t["floor"] - explode - margin)
        hi = (m["L"] + t["east"] + explode + margin, m["W"] + t["north"] + explode + margin,
              m["H"] + t["ceiling"] + explode + margin)
        aspect = tuple(h - l for l, h in zip(lo, hi))
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(aspect, zoom=zoom)
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_zlabel("z (mm)")


def draw_surface(ax, m, name):
    """2D layout of one surface: panels (cut pieces shaded), seams and the door."""
    from matplotlib.patches import Rectangle
    s = m["surfaces"][name]
    for k, ((x0, y0, x1, y1), full) in enumerate(s["pieces"], 1):
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor="#e8eef5" if full else "#f6d7c3",
                               edgecolor="#333333", linewidth=0.8))
        label = panel_id(name, k) + ("" if full else f"\n{x1 - x0:.0f} x {y1 - y0:.0f}")
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, label, ha="center", va="center",
                fontsize=7, clip_on=True)
    if s["door"]:
        x0, y0, x1, y1 = s["door"]
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor="none",
                               edgecolor="#b00020", linewidth=1.6, linestyle="--"))
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, f"DOOR\n{x1 - x0:.0f} x {y1 - y0:.0f}",
                ha="center", va="center", color="#b00020", fontsize=8)
    ax.set_xlim(-0.02 * s["w"], 1.02 * s["w"])
    ax.set_ylim(-0.04 * s["h"], 1.04 * s["h"])
    ax.set_aspect("equal")
    ax.set_title(f"{name.capitalize()}  {s['w']:.0f} x {s['h']:.0f} mm "
                 f"(board {m['board_t'][name]:g} mm)", fontsize=9)
    ax.set_xlabel("mm")
    ax.set_ylabel("mm")

