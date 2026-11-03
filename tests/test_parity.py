"""The CLI and the shared export functions must produce the same files."""
import json
import os

import pytest

import dxfutil
from chamber import cli, core, exporters
from helpers import ROOT, variants

TEXT = ["bom.csv", "panel_cutlist.csv", "hatflat_cutlist.csv", "summary.txt"]
DXF = ["chamber.dxf", "chamber_3d.dxf", "chamber_3d_exploded.dxf"]


def read(path):
    with open(path, "rb") as f:
        return f.read()


def assert_same_outputs(a, b):
    for name in TEXT + ["chamber_3d.png"]:
        assert read(os.path.join(a, name)) == read(os.path.join(b, name)), name
    for name in DXF:
        assert dxfutil.digest(os.path.join(a, name)) == dxfutil.digest(os.path.join(b, name)), name


@pytest.mark.parametrize("name", ["example", "door_west", "straight", "corners", "odd_sizes"])
def test_cli_matches_export_all(tmp_path, name):
    cfg_path = tmp_path / "c.json"
    cfg_path.write_text(json.dumps(variants()[name]))
    cli_out, api_out = tmp_path / "cli", tmp_path / "api"
    assert cli.main([str(cfg_path), "-o", str(cli_out)]) == 0
    exporters.export_all(core.build(variants()[name]), str(api_out))
    assert_same_outputs(str(cli_out), str(api_out))


def test_export_all_writes_every_file(tmp_path):
    res = exporters.export_all(core.build(variants()["example"]), str(tmp_path / "new" / "dir"))
    assert sorted(os.listdir(tmp_path / "new" / "dir")) == sorted(exporters.FILES.values())
    assert all(res["paths"].values())


def test_preview_does_not_change_the_matplotlib_backend(tmp_path):
    import matplotlib
    before = matplotlib.get_backend()
    exporters.preview(core.build(variants()["example"]), str(tmp_path))
    assert matplotlib.get_backend() == before


def test_cli_prints_the_summary_then_the_paths(tmp_path, capsys):
    cli.main([os.path.join(ROOT, "example_config.json"), "-o", str(tmp_path)])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Internal : 4000 x 3000 x 2400 mm"
    assert [ln.split(":")[0] for ln in lines[5:]] == ["DXF", "3D DXF", "3D DXF (exploded)", "Preview"]


def test_merged_3d_drawing_is_not_clipped_so_zooming_in_keeps_the_whole_chamber():
    from matplotlib.figure import Figure
    from chamber import render
    ax = Figure().add_subplot(projection="3d")
    render.draw_chamber(ax, core.build(variants()["example"]), merged=True, margin=100, zoom=2.6)
    assert ax.collections and not any(c.get_clip_on() for c in ax.collections)
