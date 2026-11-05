"""Pack loader checks: python -m pytest tests/test_pack.py (or just run the file)."""
import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lorequest.pack import Pack, PackError  # noqa: E402

PACKS = ["packs/template", "packs/lighthouse"]


def _data(path):
    return yaml.safe_load((ROOT / path / "pack.yaml").read_text(encoding="utf-8"))


def test_packs_load():
    for p in PACKS:
        pack = Pack.load(ROOT / p)
        assert pack.locations and pack.next_id(pack.locations[-1].id) == "final"


def test_render_has_custom_option():
    for p in PACKS:
        for loc in Pack.load(ROOT / p).locations:
            text = loc.render()
            assert f"{loc.custom_key}. {loc.custom_label}" in text
            assert all(f"{i}. " in text for i in range(1, len(loc.options) + 1))


def test_secret_and_eggs():
    pack = Pack.load(ROOT / "packs/lighthouse")
    assert pack.is_secret("Let there be light!") and pack.is_secret("  LET THERE BE LIGHT ")
    assert "Not yet" in pack.find_egg("let there be light", "landing")   # before the secret location: a hint
    assert "Words that old" in pack.find_egg("let there be light", None)  # after the final: an easter egg
    assert pack.find_egg("Who are you?!", "landing")
    assert pack.find_egg("something unrelated", "landing") is None


def test_facts_are_attached_by_code():
    pack = Pack.load(ROOT / "packs/lighthouse")
    used: list[str] = []
    assert "beacon" in pack.find_fact("Light a signal fire on the rocks.", used)
    assert pack.find_fact("Say nothing", used) is None


def test_broken_packs_are_rejected():
    base = _data("packs/template")
    cases = {
        "missing ui section": lambda d: d.pop("ui"),
        "no locations": lambda d: d.update(locations=[]),
        "too few options": lambda d: d["locations"][0].update(options=["one"]),
        "missing bridge_premise": lambda d: d["locations"][0].pop("bridge_premise"),
        "secret in a non-existent location": lambda d: d["secret_ending"].update(location="nope"),
    }
    for name, mutate in cases.items():
        d = copy.deepcopy(base)
        mutate(d)
        try:
            Pack(d, ROOT / "packs/template")
        except PackError:
            continue
        raise AssertionError(f"a pack with '{name}' must be rejected")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
