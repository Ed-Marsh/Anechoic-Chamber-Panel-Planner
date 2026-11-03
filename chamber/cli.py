"""Command line front end: python chamber.py config.json -o out_dir"""
import argparse
import json
import sys

from chamber import core, exporters


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Anechoic chamber panel planner. Writes chamber.dxf, bom.csv, "
                    "panel_cutlist.csv, hatflat_cutlist.csv and summary.txt.",
        epilog="python chamber.py --example > config.json prints a starting config.")
    ap.add_argument("config", nargs="?")
    ap.add_argument("-o", "--out", default="out")
    ap.add_argument("--example", action="store_true", help="print example config")
    a = ap.parse_args(argv)
    if a.example or not a.config:
        print(json.dumps(core.EXAMPLE, indent=2))
        return 0
    try:
        with open(a.config) as f:
            cfg = json.load(f)
    except OSError as e:
        print(f"error: cannot read {a.config}: {e.strerror}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {a.config} is not valid JSON: {e}", file=sys.stderr)
        return 1
    try:
        m = core.build(cfg)
    except core.ConfigError as e:
        print(f"error: {a.config}:", file=sys.stderr)
        for path, msg in e.issues:
            print(f"  {path + ': ' if path else ''}{msg}", file=sys.stderr)
        return 1
    res = exporters.export_all(m, a.out)
    print(res["plan"]["summary"], end="")
    paths = res["paths"]
    print("DXF:", paths["dxf_2d"])
    print("3D DXF:", paths["dxf_3d"])
    print("3D DXF (exploded):", paths["dxf_3d_exploded"])
    print("Preview:", paths["png"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
