"""min_panel: no slivers from row/column ends, honest warnings for door-forced ones."""
import copy
import itertools

import pytest

from chamber import core
from helpers import example, variants
from test_geometry import area, overlap_area

EPS = 0.01
VARIANTS = variants()


def with_min(cfg, mp):
    cfg = copy.deepcopy(cfg)
    cfg["min_panel"] = mp
    return cfg


def undersize(m, mp):
    """(surface, piece id suffix) for every piece with a side under mp."""
    out = []
    for n, s in m["surfaces"].items():
        for k, ((x0, y0, x1, y1), _) in enumerate(s["pieces"], 1):
            if min(x1 - x0, y1 - y0) < mp - EPS:
                out.append(core.panel_id(n, k))
    return out


# ---- balance_ends
def test_balance_ends_shifts_the_joint_so_the_end_piece_is_the_minimum():
    assert core.balance_ends([0, 2440, 2826.8], 2440, 500) == pytest.approx([0, 2326.8, 2826.8])


def test_balance_ends_merges_when_the_two_pieces_fit_on_one_sheet():
    assert core.balance_ends([0, 1000, 1200], 2440, 500) == [0, 1200]


def test_balance_ends_fixes_a_short_first_piece_too():
    assert core.balance_ends([0, 300, 2740], 2440, 500) == pytest.approx([0, 500, 2740])


def test_balance_ends_is_a_no_op_when_off_or_already_fine():
    pts = [0, 2440, 2826.8]
    assert core.balance_ends(pts, 2440, 0) is pts
    assert core.balance_ends(pts, 2440, 300) == pts


# ---- on the real model
def test_default_is_off_and_changes_nothing():
    a = core.build(example())
    b = core.build(with_min(example(), 0))
    assert [s["pieces"] for s in a["surfaces"].values()] == [s["pieces"] for s in b["surfaces"].values()]
    assert core.compute_plan(a)["warnings"] == []


def test_example_loses_its_386_mm_sliver():
    assert any(abs(min(x1 - x0, y1 - y0) - 386.8) < 0.1
               for s in core.build(example())["surfaces"].values() for (x0, y0, x1, y1), _ in s["pieces"])
    m = core.build(with_min(example(), 500))
    assert not any(abs(min(x1 - x0, y1 - y0) - 386.8) < 0.1
                   for s in m["surfaces"].values() for (x0, y0, x1, y1), _ in s["pieces"])


@pytest.mark.parametrize("mp", [300, 500, 600])
@pytest.mark.parametrize("name", VARIANTS)
def test_layout_stays_valid(name, mp):
    m = core.build(with_min(VARIANTS[name], mp))
    for n, s in m["surfaces"].items():
        rects = [p for p, _ in s["pieces"]]
        total = sum(area(r) for r in rects) + (area(s["door"]) if s["door"] else 0)
        assert total == pytest.approx(s["w"] * s["h"], abs=1.0), n
        for a, b in itertools.combinations(rects, 2):
            assert overlap_area(a, b) < EPS, (n, a, b)
        if s["door"]:
            assert all(overlap_area(r, s["door"]) < EPS for r in rects)
        long_, short = max(m["sheet"]), min(m["sheet"])
        for x0, y0, x1, y1 in rects:
            a, b = sorted((x1 - x0, y1 - y0), reverse=True)
            assert a <= long_ + EPS and b <= short + EPS, (n, a, b)


@pytest.mark.parametrize("mp", [300, 500, 600])
@pytest.mark.parametrize("name", VARIANTS)
def test_warnings_list_exactly_the_undersize_pieces_and_only_door_ones(name, mp):
    m = core.build(with_min(VARIANTS[name], mp))
    warnings = core.compute_plan(m)["warnings"]
    assert sorted(w.split()[0] for w in warnings) == sorted(undersize(m, mp))
    for w in warnings:
        assert "next to the door opening" in w, w


# ---- sweep: with no door the option must leave no undersize piece at all
SIZES = [(L, W, H) for L in (3000, 3517, 4000, 4863, 5230, 6100)
         for W in (2500, 3000, 3710) for H in (2300, 2400, 2650, 2791)]


@pytest.mark.parametrize("stagger", [0.5, 0.33, 0])
@pytest.mark.parametrize("mp", [400, 600])
def test_no_slivers_without_a_door_across_many_sizes(mp, stagger):
    for L, W, H in SIZES:
        cfg = with_min(example(), mp)
        cfg.pop("door")
        cfg.update(stagger=stagger, internal={"length": L, "width": W, "height": H})
        m = core.build(cfg)
        assert undersize(m, mp) == [], (L, W, H)
        for s in m["surfaces"].values():
            assert sum(area(p) for p, _ in s["pieces"]) == pytest.approx(s["w"] * s["h"], abs=1.0)


@pytest.mark.parametrize("mp", [400, 600])
def test_neighbouring_rows_never_share_a_joint(mp):
    for L, W, H in SIZES:
        cfg = with_min(example(), mp)
        cfg.pop("door")
        cfg["internal"] = {"length": L, "width": W, "height": H}
        m = core.build(cfg)
        for n, s in m["surfaces"].items():
            joints = {}
            for (x0, y0, x1, y1), _ in s["pieces"]:
                joints.setdefault(round(y0, 1), set()).add(round(x1, 1))
            rows = [sorted(j - {round(s["w"], 1)}) for _, j in sorted(joints.items())]
            for a, b in zip(rows, rows[1:]):
                assert not any(abs(x - y) < 1.0 for x in a for y in b), (n, L, W, H)


# ---- validation
def test_min_panel_validation():
    bad = dict(core.validate_config(with_min(example(), -5))[1])
    assert "at least 0" in bad["min_panel"]
    bad = dict(core.validate_config(with_min(example(), 700))[1])
    assert "at most 610" in bad["min_panel"]
    assert core.validate_config(with_min(example(), 610))[1] == []
