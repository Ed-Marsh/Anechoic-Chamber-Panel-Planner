"""PyInstaller entry point for ChamberPlanner.exe (windowed GUI)."""
import sys

from chamber.gui import main

if __name__ == "__main__":
    sys.exit(main())
