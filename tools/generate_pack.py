"""Interactive pack generator: asks for every item itself, no Telegram needed (only a running Ollama).

    python tools/generate_pack.py

It runs exactly the code behind the bot's /create command, so it is the quickest way to see how your local model copes
with the generator (schema-constrained JSON, the repair loop, timings). Every question can also be given as an option
(--topic, --scenes, --hero, --model, --url, --out, --lang); with --yes there is no confirmation. Missing items are asked.
Model/URL: option, then .env, then environment variables, then (for the model) the only installed one.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lorequest.config import _read_dotenv  # noqa: E402
from lorequest.core.generator import (MAX_SCENES, MIN_SCENES, TOPIC_MAX, TOPIC_MIN, GenerationError,  # noqa: E402
                                      GenRequest, generate_pack, normalize_hero, normalize_topic)
from lorequest.core.llm import LLM  # noqa: E402
from lorequest.core.pack import Pack  # noqa: E402

TXT = {
    "en": {
        "title": "lorequest pack generator (no Telegram needed)",
        "down": "Ollama is not reachable. Start it (the app, a container or `ollama serve`) and check the URL.",
        "model_q": "Model", "model_bad": "Model '{m}' is not installed in Ollama. Installed: {have}",
        "topic_q": f"Quest topic ({TOPIC_MIN}-{TOPIC_MAX} characters)",
        "scenes_q": f"Number of scenes ({MIN_SCENES}-{MAX_SCENES})",
        "hero_q": "Hero's name (2-30 letters; the narrator will use it)",
        "invalid": "  Not valid, try again.", "summary": "\nTopic:  {topic}\nScenes: {n}\nHero:   {hero}\nModel:  {model}",
        "go_q": "Generate? (takes a few minutes on a local model)", "aborted": "Aborted.", "eof": "\nNo more input, stopping.",
        "step": {"frame": "designing the story frame", "scene": "scene {i} of {n}", "save": "validating and saving"},
        "failed": "\nFAILED after {s:.0f}s: {e}\n(Rejected attempts are logged above; try again or use a stronger model.)",
        "done": "\nDone in {s:.0f}s: {path}\nTitle: {title} | language: {lang} | scenes: {n}",
        "play_q": "Start the bot with this pack now?", "play_cmd": "Play it:  python bot.py --pack {folder}",
        "yn": "[Y/n]", "ny": "[y/N]",
    },
    "ru": {
        "title": "Генератор паков lorequest (Telegram не нужен)",
        "down": "Ollama недоступна. Запустите её (приложение, контейнер или `ollama serve`) и проверьте URL.",
        "model_q": "Модель", "model_bad": "Модели '{m}' нет в Ollama. Установлены: {have}",
        "topic_q": f"Тема квеста ({TOPIC_MIN}-{TOPIC_MAX} символов)",
        "scenes_q": f"Число сцен ({MIN_SCENES}-{MAX_SCENES})",
        "hero_q": "Имя героя (2-30 букв; так рассказчик будет обращаться к игроку)",
        "invalid": "  Не подходит, попробуйте ещё раз.", "summary": "\nТема:   {topic}\nСцен:   {n}\nГерой:  {hero}\nМодель: {model}",
        "go_q": "Генерировать? (на локальной модели это несколько минут)", "aborted": "Отменено.", "eof": "\nВвод закончился, выхожу.",
        "step": {"frame": "придумываю каркас истории", "scene": "сцена {i} из {n}", "save": "проверяю и сохраняю"},
        "failed": "\nНЕ УДАЛОСЬ за {s:.0f} с: {e}\n(Отклонённые попытки выведены выше; попробуйте ещё раз или возьмите модель сильнее.)",
        "done": "\nГотово за {s:.0f} с: {path}\nНазвание: {title} | язык: {lang} | сцен: {n}",
        "play_q": "Запустить бота с этим паком сейчас?", "play_cmd": "Сыграть:  python bot.py --pack {folder}",
        "yn": "[Д/н]", "ny": "[д/Н]",
    },
}


def ask(prompt: str, check, default=None, t=None):
    """Ask until `check(answer)` returns a value (not None). Empty answer = `default` when there is one."""
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            raw = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            raise SystemExit(t["eof"] if t else "")
        if not raw and default is not None:
            return default
        value = check(raw)
        if value is not None:
            return value
        print(t["invalid"] if t else "  Invalid.")


def confirm(prompt: str, default_yes: bool, t: dict) -> bool:
    hint = t["yn"] if default_yes else t["ny"]
    try:
        raw = input(f"{prompt} {hint} ").strip().lower()
    except EOFError:
        return False
    return default_yes if not raw else raw[0] in "yд"


async def installed_models(url: str) -> list[str]:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
            async with s.get(f"{url}/api/tags") as r:
                return [m["name"] for m in (await r.json()).get("models", [])]
    except Exception:
        return []


def pick_language(arg: str | None) -> str:
    if arg:
        return arg if arg in TXT else "en"
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
        return cfg.get("operator_language", "en") if cfg.get("operator_language") in TXT else "en"
    except Exception:
        return "en"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic"), ap.add_argument("--scenes", type=int), ap.add_argument("--hero")
    ap.add_argument("--model"), ap.add_argument("--url"), ap.add_argument("--lang", choices=sorted(TXT))
    ap.add_argument("--out", default=str(ROOT / "packs" / "generated"))
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = ap.parse_args()
    t = TXT[pick_language(a.lang)]

    dotenv = _read_dotenv(ROOT / ".env")
    url = (a.url or dotenv.get("OLLAMA_URL") or os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
    print(f"=== {t['title']} ===\nOllama: {url}")
    pack = Pack.load(ROOT / "packs" / "template")  # only needed to construct the client
    probe = LLM(pack, url, "-")
    if not await probe.wait_ready(timeout=5):
        print(t["down"])
        return 2

    have = await installed_models(url)
    default_model = a.model or dotenv.get("OLLAMA_MODEL") or os.environ.get("OLLAMA_MODEL") or (have[0] if len(have) == 1 else "qwen3:8b")
    model = a.model or ask(t["model_q"], lambda m: m, default_model, t)
    while have and model not in have:  # the typical "wrong model name" mistake is caught here, not after minutes of waiting
        print(t["model_bad"].format(m=model, have=", ".join(have)))
        model = ask(t["model_q"], lambda m: m, have[0], t)

    topic = normalize_topic(a.topic) if a.topic else ask(t["topic_q"], normalize_topic, None, t)
    scenes = a.scenes if a.scenes and MIN_SCENES <= a.scenes <= MAX_SCENES else ask(
        t["scenes_q"], lambda s: int(s) if s.isdigit() and MIN_SCENES <= int(s) <= MAX_SCENES else None, 3, t)
    hero = normalize_hero(a.hero) if a.hero else ask(t["hero_q"], normalize_hero, None, t)
    if not (topic and hero):
        print(t["invalid"])
        return 2

    print(t["summary"].format(topic=topic, n=scenes, hero=hero, model=model))
    if not a.yes and not confirm(t["go_q"], True, t):
        print(t["aborted"])
        return 0

    started = time.time()

    async def progress(stage: str, i: int, n: int):
        print(f"[{time.time() - started:6.1f}s] {t['step'][stage].format(i=i, n=n)}...", flush=True)

    try:
        folder = await generate_pack(LLM(pack, url, model), GenRequest(topic, scenes, hero), Path(a.out), progress)
    except GenerationError as e:
        print(t["failed"].format(s=time.time() - started, e=e))
        return 1
    made = Pack.load(folder)
    print(t["done"].format(s=time.time() - started, path=folder / "pack.yaml", title=made.meta["title"],
                           lang=made.meta["language"], n=len(made.locations)))
    print(t["play_cmd"].format(folder=folder.as_posix()))
    if not a.yes and confirm(t["play_q"], False, t):
        os.execv(sys.executable, [sys.executable, str(ROOT / "bot.py"), "--pack", str(folder)])
    return 0


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
