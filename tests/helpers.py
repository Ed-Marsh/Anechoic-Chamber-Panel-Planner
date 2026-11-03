import copy
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def example():
    with open(os.path.join(ROOT, "example_config.json")) as f:
        return json.load(f)


def variants():
    """Named configs that exercise the door on each wall, no door, straight grid, etc."""
    ex = example()
    out = {"example": ex}
    for wall, off in (("north", 500), ("south", 1000), ("east", 700), ("west", 1500)):
        c = copy.deepcopy(ex)
        c["door"] = {"wall": wall, "offset": off, "width": 900, "height": 2000}
        out["door_" + wall] = c
    c = copy.deepcopy(ex)
    del c["door"]
    out["no_door"] = c
    c = copy.deepcopy(ex)
    c["stagger"] = 0
    out["straight"] = c
    c = copy.deepcopy(ex)
    c["corner_joints"] = True
    out["corners"] = c
    c = copy.deepcopy(ex)
    c.update(sheet={"length": 2400, "width": 1200}, stagger=0.33, kerf=5,
             internal={"length": 5230, "width": 3710, "height": 2650},
             thickness_override={"floor": 30, "west": 18})
    out["odd_sizes"] = c
    return out
