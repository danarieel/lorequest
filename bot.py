"""Launcher: `python bot.py [--pack packs/lighthouse] [--deliver] [--reset]`.

Adds `src/` to the import path so the project runs straight from a clone, without installing it.
(After `pip install -e .` the same thing is available as `python -m lorequest` or the `lorequest` command.)
Run it from the repository root: relative paths (.env, config.json, packs/, data/) are resolved from the current folder.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from lorequest.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
