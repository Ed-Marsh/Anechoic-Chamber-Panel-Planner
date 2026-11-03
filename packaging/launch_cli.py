"""PyInstaller entry point for chamber-cli.exe (console build of the command line)."""
import sys

from chamber.cli import main

if __name__ == "__main__":
    sys.exit(main())
