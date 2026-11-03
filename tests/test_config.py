"""Config defaults, validation messages and CLI error handling."""
import copy
import json
import subprocess
import sys

import pytest

from chamber import cli, core
from helpers import ROOT, example


def issues_for(cfg):
    return dict(core.validate_config(cfg)[1])


def test_door_that_does_not_fit_gives_a_clear_error():
    cfg = example()
    cfg["door"]["offset"] = 3500          # 3500 + 900 runs past the 4046.8 mm wall
    with pytest.raises(core.ConfigError) as e:
        core.build(cfg)
    assert "Door does not fit within the wall" in str(e.value)
    assert "door.width" in dict(e.value.issues)


def test_door_taller_than_the_chamber_is_rejected():
    cfg = example()
    cfg["door"]["height"] = 2500
    assert "Door does not fit within the wall" in issues_for(cfg)["door.height"]


def test_other_bad_values_name_the_field():
    cfg = example()
    cfg["internal"]["length"] = -5
    cfg["sheet"]["width"] = "wide"
    cfg["door"]["wall"] = "roof"
    cfg["thickness_override"]["roof"] = 12
    bad = issues_for(cfg)
    assert "greater than 0" in bad["internal.length"]
    assert bad["sheet.width"] == "Width must be a number"
    assert "north, south, east or west" in bad["door.wall"]
    assert "Unknown surface 'roof'" in bad["thickness_override.roof"]


def test_non_object_config_is_an_error_not_a_crash():
    with pytest.raises(core.ConfigError):
        core.build([1, 2, 3])


def test_missing_optional_keys_use_defaults():
    cfg = example()
    for key in ("steel_thickness", "thickness_override", "corner_joints", "stagger", "kerf", "door"):
        del cfg[key]
    del cfg["hat_flat"]["end_clearance"]
    del cfg["hat_flat"]["screw_pitch"]
    m = core.build(cfg)
    assert m["cfg"]["stagger"] == 0.5 and m["cfg"]["kerf"] == 3
    assert m["cfg"]["hat_flat"]["flat_thickness"] == 3
    assert m["cfg"]["hat_flat"]["draw_in_3d"] is True
    assert m["door"] is None
    assert m["t"]["floor"] == 22          # no steel, no override


def test_empty_config_still_builds_from_the_defaults():
    m = core.build({})
    assert (m["L"], m["W"], m["H"]) == (4000, 3000, 2400)


def test_unknown_keys_are_ignored_and_input_is_not_mutated():
    cfg = example()
    cfg["future_option"] = {"a": 1}
    before = copy.deepcopy(cfg)
    m = core.build(cfg)
    assert cfg == before
    assert m["cfg"]["future_option"] == {"a": 1}


def test_stagger_zero_gives_the_straight_grid():
    cfg = example()
    cfg["stagger"] = 0
    cfg.pop("door")
    m = core.build(cfg)
    for s in m["surfaces"].values():
        # every row starts and ends its pieces at the same x positions
        columns = {(x0, x1) for (x0, y0, x1, y1), _ in s["pieces"]}
        rows = {(y0, y1) for (x0, y0, x1, y1), _ in s["pieces"]}
        assert len(s["pieces"]) == len(columns) * len(rows)


def test_stagger_offsets_alternate_rows():
    cfg = example()
    cfg.pop("door")
    m = core.build(cfg)
    checked = 0
    for s in m["surfaces"].values():
        joints = {}
        for (x0, y0, x1, y1), _ in s["pieces"]:
            joints.setdefault(y0, set()).add(round(x1, 1))
        rows = [joints[y] for y in sorted(joints)]
        for a, b in zip(rows, rows[1:]):
            assert a != b          # neighbouring rows must not share joint positions
            checked += 1
    assert checked > 0


def test_summary_numbers_for_the_example():
    plan = core.compute_plan(core.build(example()))
    assert plan["full_count"] == 4 and plan["cut_count"] == 26
    assert plan["sheets_for_cuts"] == 18 and plan["total_sheets"] == 22
    assert plan["total_hf"] / 1000 == pytest.approx(46.72, abs=0.005)
    assert plan["bar_count"] == 20
    assert tuple(round(v, 1) for v in plan["external"]) == (4046.8, 3046.8, 2446.8)


def test_core_does_not_print(capsys):
    plan = core.compute_plan(core.build(example()))
    core.solids(core.build(example()), 50)
    assert plan["summary"].startswith("Internal")
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


# ---- CLI error handling
def run_cli(*args):
    return subprocess.run([sys.executable, "chamber.py", *args], cwd=ROOT,
                          capture_output=True, text=True)


def test_cli_reports_a_bad_door_without_a_traceback(tmp_path):
    cfg = example()
    cfg["door"]["offset"] = 3500
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(cfg))
    res = run_cli(str(path), "-o", str(tmp_path / "out"))
    assert res.returncode == 1
    assert "Door does not fit within the wall" in res.stderr
    assert "Traceback" not in res.stderr
    assert not (tmp_path / "out").exists()


def test_cli_reports_missing_and_malformed_files(tmp_path):
    res = run_cli(str(tmp_path / "nope.json"))
    assert res.returncode == 1 and "cannot read" in res.stderr
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    res = run_cli(str(bad))
    assert res.returncode == 1 and "not valid JSON" in res.stderr


def test_cli_example_prints_the_example_config():
    res = run_cli("--example")
    assert json.loads(res.stdout) == core.EXAMPLE
    assert cli.main(["--example"]) == 0
