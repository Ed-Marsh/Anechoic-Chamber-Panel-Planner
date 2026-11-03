"""GUI smoke tests. Skipped when there is no display (headless CI on Linux)."""
import json
import os
import time
import tkinter as tk

import pytest

import dxfutil
from chamber import cli, exporters
from helpers import ROOT, example

EXAMPLE_PATH = os.path.join(ROOT, "example_config.json")


def _display_available():
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


pytestmark = pytest.mark.skipif(not _display_available(), reason="no display available")


@pytest.fixture
def app(tmp_path):
    from chamber.gui import ChamberApp
    try:
        a = ChamberApp(settings_file=str(tmp_path / "settings.json"))
    except tk.TclError:
        # Tk start-up fails now and then on the Windows dev machine ("couldn't read file
        # menu.tcl"), inside tk.Tk() itself and only under pytest. One retry is enough.
        time.sleep(0.5)
        a = ChamberApp(settings_file=str(tmp_path / "settings.json"))
    a.withdraw()
    yield a
    a.modified = False
    a.destroy()


def test_loads_the_example_and_recomputes(app):
    assert app.load_config_file(EXAMPLE_PATH)
    assert app.recompute_now()
    assert app.plan["total_sheets"] == 22
    assert len(app.panel_tree.get_children()) == 30
    assert app.fields["internal.length"].var.get() == "4000"
    assert app.fields["door.enabled"].var.get() is True


def test_invalid_edit_flags_the_field_and_keeps_the_last_good_view(app):
    app.recompute_now()
    good = app.plan
    app.fields["door.offset"].var.set("3500")
    assert not app.recompute_now()
    assert "Door does not fit" in app.field_issues["door.width"]
    assert app.plan is good
    assert "last valid layout" in app.banner.cget("text")
    app.fields["door.offset"].var.set("abc")
    app.recompute_now()
    assert app.field_issues == {"door.offset": "Enter a number"}
    app.fields["door.offset"].var.set("1000")
    assert app.recompute_now()
    assert app.banner.cget("text") == ""


def test_edit_updates_the_model(app):
    app.fields["internal.length"].var.set("5000")
    assert app.recompute_now()
    assert app.model["L"] == 5000


def test_save_and_reopen_round_trips_and_keeps_unknown_keys(app, tmp_path):
    raw = example()
    raw["future_option"] = [1, 2]
    src = tmp_path / "in.json"
    src.write_text(json.dumps(raw))
    assert app.load_config_file(str(src))
    app.fields["board_thickness"].var.set("25")
    dst = tmp_path / "out.json"
    assert app.write_config(str(dst))
    saved = json.loads(dst.read_text())
    assert saved["board_thickness"] == 25 and saved["future_option"] == [1, 2]
    assert saved["internal"] == {"length": 4000, "width": 3000, "height": 2400}
    assert app.load_config_file(str(dst))
    assert app.fields["board_thickness"].var.get() == "25"


def test_disabling_the_door_drops_it_from_the_config(app):
    app.fields["door.enabled"].var.set(False)
    cfg, errors = app.form_to_cfg()
    assert "door" not in cfg and not errors
    assert app.recompute_now()
    assert app.model["door"] is None


def test_partial_config_with_unknown_keys_opens_with_defaults(app, tmp_path):
    path = tmp_path / "partial.json"
    path.write_text(json.dumps({"internal": {"length": 3000}, "mystery": True}))
    assert app.load_config_file(str(path))
    assert app.fields["internal.width"].var.get() == "3000"     # default
    assert app.fields["stagger"].var.get() == "0.5"
    assert app.model["L"] == 3000


def test_unreadable_files_do_not_crash_the_app(app, tmp_path, monkeypatch):
    from tkinter import messagebox
    shown = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: shown.append(a))
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]")
    assert not app.load_config_file(str(bad))
    assert shown and app.model is not None


def test_view_toggles_redraw_without_error(app):
    app.explode_var.set(200)
    app.surface_vars["north"].set(False)
    app.hf_var.set(False)
    app.redraw3d()
    app.zoom = 2
    app.redraw3d()
    app.reset_view()


def test_gui_export_matches_cli(app, tmp_path):
    """The GUI's model and plan, through the shared exporter, equal the CLI's files."""
    app.load_config_file(EXAMPLE_PATH)
    gui_out, cli_out = tmp_path / "gui", tmp_path / "cli"
    exporters.export_all(app.model, str(gui_out), app.plan)
    cli.main([EXAMPLE_PATH, "-o", str(cli_out)])
    for name in ("bom.csv", "panel_cutlist.csv", "hatflat_cutlist.csv", "summary.txt", "chamber_3d.png"):
        assert (gui_out / name).read_bytes() == (cli_out / name).read_bytes(), name
    for name in ("chamber.dxf", "chamber_3d.dxf", "chamber_3d_exploded.dxf"):
        assert dxfutil.digest(str(gui_out / name)) == dxfutil.digest(str(cli_out / name)), name


def test_settings_are_saved_on_close(tmp_path):
    path = tmp_path / "settings.json"
    from chamber.gui import ChamberApp
    a = ChamberApp(settings_file=str(path))
    a.withdraw()
    a.remember_folder(str(tmp_path))
    a.on_close()
    saved = json.loads(path.read_text())
    assert saved["last_dir"] == str(tmp_path) and "x" in saved["geometry"]
