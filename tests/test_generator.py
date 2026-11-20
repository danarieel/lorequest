"""Checks for the pack generator (no Ollama needed): python tests/test_generator.py"""
import asyncio
import copy
import sys
from pathlib import Path

import yaml
from aiohttp import web

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import gen_fakes  # noqa: E402
from lorequest.core import generator as g  # noqa: E402
from lorequest.core.llm import LLM  # noqa: E402
from lorequest.core.pack import Pack  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_slugify_is_path_safe():
    assert g.slugify("Тайна старого маяка") == "tayna-starogo-mayaka"
    assert g.slugify("../../etc/passwd") == "etc-passwd"
    assert g.slugify("...") == "quest" and g.slugify("") == "quest"
    assert len(g.slugify("x" * 200)) <= 40
    assert "/" not in g.slugify("a/b\\c:d")


def test_unique_dir_never_overwrites(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "story").mkdir()
        (root / "story-2").mkdir()
        assert g.unique_dir(root, "story").name == "story-3"


def test_language_detection_and_name_stem():
    assert g.GenRequest("Тайна маяка", 3, "Алекс").language == "ru"
    assert g.GenRequest("A haunted lighthouse", 3, "Alex").language == "en"
    assert g.name_stem("Алексей", "ru") == "алекс"      # Russian names are inflected: only the beginning is required
    assert g.name_stem("Alex", "en") == "alex"


def test_validators_explain_what_is_wrong():
    req = g.GenRequest("A haunted lighthouse", 3, "Alex")
    good = gen_fakes.scene(req, 1)
    assert g.validate_scene(good, req, 1) is None
    bad = dict(good, options=["only", "two"])
    assert "exactly 3" in g.validate_scene(bad, req, 1)
    bad = dict(good, fallback="The narrator nods. The storm will remember this.")
    assert "Alex" in g.validate_scene(bad, req, 1)
    bad = dict(good, bridge_premise="")
    assert "bridge_premise" in g.validate_scene(bad, req, 1)           # not the last scene: a bridge is required
    assert g.validate_scene(dict(good, bridge_premise=""), req, 3) is None  # the last scene needs none
    assert "outline" in g.validate_frame(dict(gen_fakes.frame(req), outline=["one sentence only here"]), req)


def test_generate_pack_end_to_end():
    import tempfile
    for topic, hero, lang in (("A haunted lighthouse", "Alex", "en"), ("Тайна старого маяка", "Алекс", "ru")):
        req = g.GenRequest(topic, 3, hero)
        with tempfile.TemporaryDirectory() as tmp:
            steps = []

            async def progress(stage, i, n):
                steps.append((stage, i))

            folder = run(g.generate_pack(gen_fakes.FakeLLM(req), req, Path(tmp), progress))
            pack = Pack.load(folder)                                   # the saved file loads with the real loader
            assert pack.meta["language"] == lang and len(pack.locations) == 3
            assert steps == [("frame", 0), ("scene", 1), ("scene", 2), ("scene", 3), ("save", 3)]
            assert all(loc.image is None and loc.image_prompt for loc in pack.locations)   # prompt, NOT a file name
            assert pack.locations[0].bridge_premise and pack.locations[-1].bridge_premise is None
            assert pack.validation["required_substring"] == g.name_stem(hero, lang)
            assert folder.parent == Path(tmp) and folder.name.replace("-", "").isalnum()


def test_repair_loop_sends_the_validator_error_back():
    import tempfile
    req = g.GenRequest("A haunted lighthouse", 2, "Alex")
    broken = dict(gen_fakes.scene(req, 1), options=["only", "two"])
    # frame is fine, scene 1: first answer is invalid JSON-content, second still wrong, third fine
    script = [gen_fakes.frame(req), "not json at all", broken]
    llm = gen_fakes.FakeLLM(req, script)
    llm._scene_no = 0
    with tempfile.TemporaryDirectory() as tmp:
        folder = run(g.generate_pack(llm, req, Path(tmp)))
        assert len(Pack.load(folder).locations) == 2
    retry_calls = [c for c in llm.calls if "outline" not in c["schema"]["properties"]][:3]
    last_user = retry_calls[1]["messages"][-1]["content"]
    assert "not valid JSON" in last_user                                # 2nd attempt: the parse error was reported
    assert "exactly 3" in retry_calls[2]["messages"][-1]["content"]     # 3rd attempt: the content error was reported
    assert retry_calls[2]["messages"][-2]["role"] == "assistant"        # ...together with the model's own previous answer


def test_gives_up_after_three_attempts_and_cancel_works():
    import tempfile
    req = g.GenRequest("A haunted lighthouse", 2, "Alex")
    llm = gen_fakes.FakeLLM(req, ["nope", "nope", "nope"])
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run(g.generate_pack(llm, req, Path(tmp)))
            raise AssertionError("must fail")
        except g.GenerationError as e:
            assert "story frame" in str(e)
        assert not list(Path(tmp).iterdir())                           # nothing is left on disk
        try:
            run(g.generate_pack(gen_fakes.FakeLLM(req), req, Path(tmp), cancelled=lambda: True))
            raise AssertionError("must cancel")
        except g.GenerationCancelled:
            pass


def test_markup_from_the_model_is_neutralised():
    import tempfile
    req = g.GenRequest("A haunted lighthouse", 2, "Alex")
    frame = gen_fakes.frame(req)
    scene1 = dict(gen_fakes.scene(req, 1), body="**Bold** <script>x</script> Tom & Jerry {evil} wait here for Alex tonight, in the dark.")
    llm = gen_fakes.FakeLLM(req, [frame, scene1])
    with tempfile.TemporaryDirectory() as tmp:
        folder = run(g.generate_pack(llm, req, Path(tmp)))
        body = Pack.load(folder).locations[0].body
        assert "<" not in body and "{" not in body and "*" not in body
        assert "&amp;" in body                                          # the text is sent as Telegram HTML


def test_chat_json_http_layer():
    """The real LLM.chat_json against a tiny fake Ollama: sends `format`, and retries without `think` on HTTP 400."""
    seen = []

    async def handler(request):
        payload = await request.json()
        seen.append(payload)
        if "think" in payload:
            return web.json_response({"error": "model does not support think"}, status=400)
        return web.json_response({"message": {"content": '{"ok": true}'}})

    async def go():
        app = web.Application()
        app.router.add_post("/api/chat", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            llm = LLM(Pack.load(ROOT / "packs/template"), f"http://127.0.0.1:{port}", "fake-model")
            schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
            return await llm.chat_json("sys", [{"role": "user", "content": "hi"}], schema)
        finally:
            await runner.cleanup()

    assert run(go()) == '{"ok": true}'
    assert seen[0]["format"]["type"] == "object" and seen[0]["messages"][0]["content"] == "sys"
    assert len(seen) == 2 and "think" not in seen[1]                    # retried without `think`


def test_input_normalisation_is_shared_by_bot_and_cli():
    assert g.normalize_topic("  A   haunted\nlighthouse ") == "A haunted lighthouse"
    assert g.normalize_topic("/start") is None and g.normalize_topic("ab") is None and g.normalize_topic("x" * 201) is None
    assert g.normalize_hero("Alex") == "Alex" and g.normalize_hero("Анна-Мария") == "Анна-Мария"
    assert g.normalize_hero("A<b>") is None and g.normalize_hero("{x}") is None and g.normalize_hero("A") is None


def test_cli_asks_every_item_interactively():
    """tools/generate_pack.py with NO options: it must ask for the model, topic, scenes, hero, confirmation, then generate."""
    import subprocess
    import tempfile
    import threading

    req = g.GenRequest("A haunted lighthouse", 2, "Alex")
    counter = {"scene": 0}

    async def tags(_):
        return web.json_response({"models": [{"name": "fake:1b"}]})

    async def chat(request):
        props = (await request.json())["format"]["properties"]
        if "outline" in props:
            return web.json_response({"message": {"content": gen_fakes.dumps(gen_fakes.frame(req))}})
        counter["scene"] += 1
        return web.json_response({"message": {"content": gen_fakes.dumps(gen_fakes.scene(req, counter["scene"]))}})

    loop, ready, stop = asyncio.new_event_loop(), threading.Event(), {}

    def serve():
        asyncio.set_event_loop(loop)
        app = web.Application()
        app.router.add_get("/api/tags", tags)
        app.router.add_post("/api/chat", chat)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", 0)
        loop.run_until_complete(site.start())
        stop["port"] = site._server.sockets[0].getsockname()[1]
        ready.set()
        loop.run_forever()

    threading.Thread(target=serve, daemon=True).start()
    assert ready.wait(10)
    try:
        answers = "\n".join(["", "x", "A haunted lighthouse", "9", "2", "A<b>", "Alex", "y", "n"]) + "\n"  # bad inputs first
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "generate_pack.py"), "--lang", "en", "--out", tmp,
                                "--url", f"http://127.0.0.1:{stop['port']}"], input=answers, capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, r.stdout + r.stderr
            assert "Not valid" in r.stdout                                    # bad topic / scene count / name were re-asked
            assert "Topic:  A haunted lighthouse" in r.stdout and "Hero:   Alex" in r.stdout
            folders = list(Path(tmp).iterdir())
            assert len(folders) == 1 and len(Pack.load(folders[0]).locations) == 2
    finally:
        loop.call_soon_threadsafe(loop.stop)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
