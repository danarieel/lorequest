"""Generate a pack from the command line, with NO Telegram involved (only a running Ollama is needed).

    python tools/generate_pack.py --topic "A haunted lighthouse" --scenes 3 --hero Alex
    python tools/generate_pack.py --topic "Тайна старого маяка" --scenes 2 --hero Алекс --model qwen3:8b

It runs exactly the code behind the bot's /create command, so it is the quickest way to check how your local model
copes with the generator (schema-constrained JSON, the repair loop, timings) before trying it in Telegram.
Model/URL come from: --model/--url, then .env, then environment variables, then defaults.
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lorequest.config import _read_dotenv  # noqa: E402
from lorequest.core.generator import MAX_SCENES, MIN_SCENES, GenerationError, GenRequest, generate_pack  # noqa: E402
from lorequest.core.llm import LLM  # noqa: E402
from lorequest.core.pack import Pack  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", required=True, help="what the quest is about (3-200 characters)")
    ap.add_argument("--scenes", type=int, default=3, help=f"number of scenes, {MIN_SCENES}-{MAX_SCENES}")
    ap.add_argument("--hero", required=True, help="the hero's name (how the narrator addresses the player)")
    ap.add_argument("--model", help="Ollama model (default: .env / OLLAMA_MODEL / qwen3:8b)")
    ap.add_argument("--url", help="Ollama URL (default: .env / OLLAMA_URL / http://localhost:11434)")
    ap.add_argument("--out", default=str(ROOT / "packs" / "generated"), help="where to save the pack")
    a = ap.parse_args()

    dotenv = _read_dotenv(ROOT / ".env")
    model = a.model or dotenv.get("OLLAMA_MODEL") or os.environ.get("OLLAMA_MODEL") or "qwen3:8b"
    url = a.url or dotenv.get("OLLAMA_URL") or os.environ.get("OLLAMA_URL") or "http://localhost:11434"
    llm = LLM(Pack.load(ROOT / "packs" / "template"), url, model)  # the pack is only needed to construct the client

    print(f"Model: {model} | Ollama: {url}")
    if not await llm.wait_ready(timeout=5):
        print("Ollama is not reachable. Start it (the tray app or `ollama serve`) and check the URL.")
        return 2

    started = time.time()

    async def progress(stage: str, i: int, n: int):
        label = {"frame": "designing the story frame", "scene": f"scene {i} of {n}", "save": "validating and saving"}[stage]
        print(f"[{time.time() - started:6.1f}s] {label}...", flush=True)

    try:
        folder = await generate_pack(llm, GenRequest(a.topic, a.scenes, a.hero), Path(a.out), progress)
    except GenerationError as e:
        print(f"\nFAILED after {time.time() - started:.0f}s: {e}")
        print("(Rejected attempts are logged above; try again, or use a stronger model.)")
        return 1
    pack = Pack.load(folder)
    print(f"\nDone in {time.time() - started:.0f}s: {folder / 'pack.yaml'}")
    print(f"Title: {pack.meta['title']} | language: {pack.meta['language']} | scenes: {len(pack.locations)}")
    print(f"Play it:  python bot.py --pack {folder.as_posix()}")
    return 0


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(asyncio.run(main()))
