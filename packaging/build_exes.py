"""Build the Windows executables with PyInstaller.

    python packaging/build_exes.py            # one-file ChamberPlanner.exe + chamber-cli.exe
    python packaging/build_exes.py --onedir   # folders instead (fewer antivirus false positives)

Output goes to dist/. This is the one place the PyInstaller options live, so a local
build and the GitHub Actions build are the same.
"""
import argparse
import os
import sys

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Packages the app never uses but PyInstaller may otherwise pull in from the environment.
EXCLUDES = ["PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "IPython", "jupyter", "notebook",
            "pandas", "scipy", "pytest", "setuptools"]

BUILDS = [
    # (exe name, entry script, windowed?)
    ("ChamberPlanner", "packaging/launch_gui.py", True),
    ("chamber-cli", "packaging/launch_cli.py", False),
]


def build(name, script, windowed, onedir):
    args = [
        os.path.join(ROOT, script),
        "--name", name,
        "--noconfirm", "--clean",
        "--onedir" if onedir else "--onefile",
        "--windowed" if windowed else "--console",
        "--paths", ROOT,
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build", name),
        "--specpath", os.path.join(ROOT, "build"),
        # ezdxf loads some modules lazily, and the Tk backend is chosen by name.
        "--collect-submodules", "ezdxf",
        "--hidden-import", "matplotlib.backends.backend_tkagg",
        "--hidden-import", "matplotlib.backends.backend_agg",
    ]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    PyInstaller.__main__.run(args)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--onedir", action="store_true", help="build folders, not single files")
    ap.add_argument("--only", choices=[b[0] for b in BUILDS], help="build just one exe")
    a = ap.parse_args()
    for name, script, windowed in BUILDS:
        if a.only in (None, name):
            build(name, script, windowed, a.onedir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
