"""Order-sensitive digest of a DXF's drawing content.

ezdxf writes a fresh timestamp, GUIDs and a hash-ordered layout section on every
save, so two identical runs are never byte-identical. This digest covers what
matters (layers and every modelspace entity) and ignores that noise.
"""
import hashlib

import ezdxf

_SKIP = {"handle", "owner"}


def _attribs(e):
    return {k: v for k, v in sorted(e.dxfattribs().items()) if k not in _SKIP}


def signature_lines(path):
    doc = ezdxf.readfile(path)
    lines = [f"layer {la.dxf.name} {la.dxf.color}" for la in doc.layers]
    for e in doc.modelspace():
        lines.append(f"{e.dxftype()} {_attribs(e)}")
        if e.dxftype() == "POLYLINE":
            for v in e.vertices:
                lines.append(f"  v {_attribs(v)}")
        elif e.dxftype() == "LWPOLYLINE":
            lines.append(f"  pts {list(e.get_points())}")
    return lines


def digest(path):
    return hashlib.sha256("\n".join(signature_lines(path)).encode()).hexdigest()
