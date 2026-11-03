"""Regression check: the CLI output for example_config.json must not change.

Golden files in tests/golden/ were produced by the original single-file
chamber.py. CSVs and summary are compared byte for byte, DXFs by an
order-sensitive digest of their entities (ezdxf stamps every file with a
timestamp and GUIDs, so raw DXF bytes differ between identical runs).
"""
import json
import os
import subprocess
import sys

import pytest

import dxfutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ROOT, "tests", "golden")
TEXT_FILES = ["bom.csv", "panel_cutlist.csv", "hatflat_cutlist.csv", "summary.txt"]


@pytest.fixture(scope="module")
def cli_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("cli") / "out"
    res = subprocess.run(
        [sys.executable, "chamber.py", "example_config.json", "-o", str(out)],
        cwd=ROOT, capture_output=True, text=True, check=True)
    return out, res.stdout


@pytest.mark.parametrize("name", TEXT_FILES)
def test_text_outputs_identical(cli_run, name):
    out, _ = cli_run
    with open(os.path.join(GOLDEN, name), "rb") as f:
        want = f.read()
    with open(out / name, "rb") as f:
        assert f.read() == want


def test_stdout_summary_identical(cli_run):
    _, stdout = cli_run
    with open(os.path.join(GOLDEN, "stdout_summary.txt"), newline="") as f:
        want = f.read().splitlines()
    assert stdout.splitlines()[:5] == want
    tail = [ln.split(":")[0] for ln in stdout.splitlines()[5:]]
    assert tail == ["DXF", "3D DXF", "3D DXF (exploded)", "Preview"]


def test_dxf_content_identical(cli_run):
    out, _ = cli_run
    with open(os.path.join(GOLDEN, "dxf_digests.json")) as f:
        want = json.load(f)
    for name, digest in want.items():
        assert dxfutil.digest(str(out / name)) == digest, name


def test_golden_numbers(cli_run):
    _, stdout = cli_run
    assert "Internal : 4000 x 3000 x 2400 mm" in stdout
    assert "External : 4046.8 x 3046.8 x 2436.8 mm" in stdout
    assert "4 full + 26 cut pieces from 18 sheets = 22 sheets" in stdout
    assert "46.72 m each, 20 x 3000 mm bars each" in stdout
