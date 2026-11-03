#!/usr/bin/env python3
"""
Anechoic chamber panel planner (command line).

Input : JSON config (all dimensions in millimetres)
Output: chamber.dxf (CAD), bom.csv, panel_cutlist.csv, hatflat_cutlist.csv, summary.txt

Usage : python chamber.py config.json -o out_dir
        python chamber.py --example > config.json

The code lives in the chamber/ package; this file keeps the old entry point working.
For the graphical front end run: python -m chamber.gui
"""
import sys

from chamber.cli import main

if __name__ == "__main__":
    sys.exit(main())
