"""Run: python bot.py --pack packs/lighthouse [--deliver] [--reset]   (or `python -m lorequest ...` after `pip install -e .`)"""
from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler

from .bot.app import QuestApp
from .config import load_settings
from .core.llm import LLM
from .core.pack import Pack, PackError
from .core.store import Store


def main(argv=None):
    settings = load_settings(argv)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(),
                  RotatingFileHandler(settings.data_dir / "bot.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")],
    )
    try:
        pack = Pack.load(settings.pack_dir)
    except PackError as e:
        raise SystemExit(f"Pack error: {e}")
    store = Store(settings.data_dir / "quest_state.json")
    llm = LLM(pack, settings.ollama_url, settings.model)
    app = QuestApp(pack, settings, store, llm)
    logging.info("Pack: %s | model: %s | mode: %s", pack.meta["title"], settings.model, "DELIVER" if settings.deliver else "SERVE")
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
