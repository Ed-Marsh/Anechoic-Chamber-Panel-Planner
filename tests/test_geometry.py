"""Geometry invariants that must hold for any valid layout."""
import itertools

import pytest

from chamber import core
from helpers import variants

CONFIGS = variants()
EPS = 0.01


def area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


def overlap_area(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


@pytest.mark.parametrize("name", CONFIGS)
def test_panels_plus_door_fill_each_surface(name):
    m = core.build(CONFIGS[name])
    for n, s in m["surfaces"].items():
        total = sum(area(p) for p, _ in s["pieces"])
        door = area(s["door"]) if s["door"] else 0.0
        assert total + door == pytest.approx(s["w"] * s["h"], abs=1.0), n


@pytest.mark.parametrize("name", CONFIGS)
def test_panels_do_not_overlap_each_other_or_the_door(name):
    m = core.build(CONFIGS[name])
    for n, s in m["surfaces"].items():
        rects = [p for p, _ in s["pieces"]]
        for a, b in itertools.combinations(rects, 2):
            assert overlap_area(a, b) < EPS, (n, a, b)
        if s["door"]:
            for r in rects:
                assert overlap_area(r, s["door"]) < EPS, (n, r)


@pytest.mark.parametrize("name", CONFIGS)
def test_panels_stay_inside_the_surface(name):
    m = core.build(CONFIGS[name])
    for n, s in m["surfaces"].items():
        for (x0, y0, x1, y1), _ in s["pieces"]:
            assert x0 >= -EPS and y0 >= -EPS and x1 <= s["w"] + EPS and y1 <= s["h"] + EPS, n


@pytest.mark.parametrize("name", CONFIGS)
def test_no_panel_is_bigger_than_a_sheet(name):
    m = core.build(CONFIGS[name])
    long_, short = max(m["sheet"]), min(m["sheet"])
    for s in m["surfaces"].values():
        for (x0, y0, x1, y1), _ in s["pieces"]:
            a, b = sorted((x1 - x0, y1 - y0), reverse=True)
            assert a <= long_ + EPS and b <= short + EPS


@pytest.mark.parametrize("name", CONFIGS)
def test_solids_have_positive_volume(name):
    m = core.build(CONFIGS[name])
    for layer, label, (x0, y0, z0, x1, y1, z1) in core.solids(m, 100):
        assert x1 > x0 and y1 > y0 and z1 > z0, (layer, label)
