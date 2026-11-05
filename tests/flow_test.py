"""Run the whole quest without Telegram or Ollama (network and model are mocked): python tests/flow_test.py"""
import asyncio
import datetime as dt
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiogram import Bot, types  # noqa: E402
from aiogram.exceptions import TelegramForbiddenError  # noqa: E402

from lorequest.bot import FREE, Q, QuestApp  # noqa: E402
from lorequest.config import Settings  # noqa: E402
from lorequest.llm import LLM  # noqa: E402
from lorequest.pack import Pack  # noqa: E402
from lorequest.store import Store  # noqa: E402

OWNER, RECIPIENT = 111111111, 222222222
OUT: list = []
FAIL_FOR: set = set()
FAILS = 0


async def fake_call(self, method, request_timeout=None):
    name = type(method).__name__
    if name == "SendChatAction":
        return True
    chat = getattr(method, "chat_id", None)
    if chat in FAIL_FOR:
        raise TelegramForbiddenError(method=method, message="Forbidden: bot can't initiate conversation with a user")
    rm = getattr(method, "reply_markup", None)
    kb = [b.text for row in rm.keyboard for b in row] if rm is not None and hasattr(rm, "keyboard") else None
    OUT.append((chat, name, getattr(method, "text", None) or getattr(method, "caption", None) or "", kb))
    return types.Message(message_id=1, date=dt.datetime.now(), chat=types.Chat(id=1, type="private"))


Bot.__call__ = fake_call


def check(cond, label):
    global FAILS
    print(("  ✅ " if cond else "  ❌ ") + label)
    FAILS += 0 if cond else 1


def sent(needle, to=None):
    return any(needle in t and (to is None or c == to) for c, _, t, _ in OUT)


def make_app(pack_dir, deliver, tmp, access="owner", allowed=frozenset()):
    pack = Pack.load(ROOT / pack_dir)
    s = Settings(token="123456:abcdef", owner_id=OWNER, recipient_id=RECIPIENT,
                 launch_at=dt.datetime.now() + dt.timedelta(hours=5), model="fake", ollama_url="http://x",
                 deliver=deliver, reset=False, access=access, allowed_ids=allowed, token_source="test",
                 operator_language="en", pack_dir=ROOT / pack_dir, data_dir=Path(tmp))
    llm = LLM(pack, s.ollama_url, s.model)

    async def fake_ask(messages, fallback, validate=True):
        return f"Reply, {pack.validation.get('required_substring') or 'ok'}. Fake model answer."

    llm.ask = fake_ask
    return QuestApp(pack, s, Store(Path(tmp) / "state.json"), llm), pack


async def run_pack(pack_dir, secret_phrase):
    print(f"\n== {pack_dir}: normal mode (/start starts the quest)")
    with tempfile.TemporaryDirectory() as tmp:
        app, pack = make_app(pack_dir, False, tmp)
        n = 0

        async def say(text, uid=OWNER, age=0):
            nonlocal n
            n += 1
            OUT.clear()
            date = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=age)
            ents = [types.MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))] if text.startswith("/") else None
            u = types.Update(update_id=n, message=types.Message(
                message_id=n, date=date, chat=types.Chat(id=uid, type="private"),
                from_user=types.User(id=uid, is_bot=False, first_name="T"), text=text, entities=ents))
            await app.dp.feed_update(app.bot, u)

        def button():
            for _, _, _, kb in reversed(OUT):
                if kb and kb[0] in pack.ui["next_phrases"]:
                    return kb[0]

        OUT.clear()
        first = pack.first
        check(not OUT, "the bot writes nothing before /start")
        await say("/start"); check(sent(pack.ui["intro"][:12]), "/start starts the quest")
        await say("/start", uid=RECIPIENT); check(not OUT, "the recipient is ignored outside delivery mode")
        await say("/start", age=3600); check(not OUT, "a stale /start is ignored")
        await say("1"); check(sent(pack.ui["press_start"]), "moves are not accepted before the start button")
        await say(pack.ui["start_button"]); check(sent(first.title), "the start button opens the first location")
        await say(pack.ui["start_button"]); check(not OUT, "a repeated start button does nothing")
        await say(secret_phrase); check(sent(pack.secret["early_reply"]), "the secret phrase before its location gives a hint")
        await say("/hint"); check(sent(pack.hints[0]), "/hint during the story")
        await say("1"); check(sent(pack.persona["speaker_label"]), "a ready-made option gets a comment")
        await say("2"); check(sent(pack.ui["waiting_confirm"]), "no move is accepted until the continue button is pressed")
        for loc in pack.locations[1:]:
            await say(button()); check(sent(loc.title), f"the button leads to '{loc.id}'")
            custom = loc.custom_key
            await say(custom); await say("blow everything up")
            if loc.bridge_premise:
                check(any(t.startswith(pack.ui["bridge_format"][:2]) for _, _, t, _ in OUT), f"{loc.id}: a free-text move produces a bridge")
        await say(button())
        check(sent(pack.final["text"][:20]), "regular final scene")
        check(any("verdict" in str(t).lower() or "verdict" in t.lower() for _, _, t, _ in OUT), "a verdict precedes the final")
        await say("/hint"); check(sent(pack.ui["hint_free"]), "no hints in free chat")
        await say("hello"); check(OUT and OUT[-1][1] == "SendMessage", "free chat replies")

        print(f"== {pack_dir}: access policy")
        for access, allowed, uid, expect in (("owner", frozenset({999}), 999, False), ("list", frozenset({999}), 999, True),
                                             ("list", frozenset({999}), 888, False), ("anyone", frozenset(), 888, True)):
            app2, _ = make_app(pack_dir, False, tmp, access=access, allowed=allowed)
            OUT.clear()
            u = types.Update(update_id=900 + uid, message=types.Message(
                message_id=1, date=dt.datetime.now(dt.timezone.utc), chat=types.Chat(id=uid, type="private"),
                from_user=types.User(id=uid, is_bot=False, first_name="T"), text="/start",
                entities=[types.MessageEntity(type="bot_command", offset=0, length=6)]))
            await app2.dp.feed_update(app2.bot, u)
            check(bool(OUT) == expect, f"access={access}: user {uid} {'is allowed' if expect else 'is ignored'}")

        print(f"== {pack_dir}: secret ending and restart")
        app.store.reset()
        await say("/start"); await say(pack.ui["start_button"])
        for loc in pack.locations[:-1]:
            await say("1"); await say(button())
        await say(secret_phrase)
        check(sent(pack.secret["text"][:20]) and sent(pack.secret.get("final_prefix", "")[:6] or pack.final["text"][:10]),
              "secret scene + final")
        check(not any("verdict" in t.lower() for _, _, t, _ in OUT), "no verdict in the secret ending")
        check((await app.dp.fsm.resolve_context(app.bot, OWNER, OWNER).get_state()) == Q.free.state, "free chat after the final")

        # "restart": FSM is empty, progress comes from the file
        app.store.reset(); app.store.save_stage(OWNER, pack.first.id)
        await app.dp.fsm.resolve_context(app.bot, OWNER, OWNER).clear()
        await say("something")
        check(sent(pack.ui["resumed"]) and sent(pack.first.title), "after a restart the player returns to their location")

        print(f"== {pack_dir}: delivery mode")
    with tempfile.TemporaryDirectory() as tmp:
        app, pack = make_app(pack_dir, True, tmp)
        n2 = 100

        async def say2(text, uid):
            nonlocal n2
            n2 += 1
            OUT.clear()
            ents = [types.MessageEntity(type="bot_command", offset=0, length=len(text))] if text.startswith("/") else None
            u = types.Update(update_id=n2, message=types.Message(
                message_id=n2, date=dt.datetime.now(dt.timezone.utc), chat=types.Chat(id=uid, type="private"),
                from_user=types.User(id=uid, is_bot=False, first_name="T"), text=text, entities=ents))
            await app.dp.feed_update(app.bot, u)

        await say2("/start", RECIPIENT)
        check(sent("Match", OWNER) and sent(pack.ui["recipient_waiting"], RECIPIENT), "before launch time: the recipient is acknowledged and the owner gets an ID check")
        await say2("/start", 999); check(not OUT, "a stranger is ignored")
        await say2("hello", RECIPIENT); check(sent(pack.ui["not_started"]), "before launch the recipient gets no quest reply")
        await app.fire_job()
        check(sent(pack.ui["intro"][:12], RECIPIENT) and sent("Quest sent", OWNER), "fire_job sent the intro and notified the owner")
        OUT.clear(); await app.fire_job(); check(not OUT, "a repeated fire_job sends nothing")
        app.s.launch_at = dt.datetime.now() - dt.timedelta(minutes=1)
        await say2(pack.ui["start_button"], RECIPIENT); check(sent(pack.first.title, RECIPIENT), "the recipient plays")
        await say2("/start", RECIPIENT)
        check(sent(pack.ui["resumed"], RECIPIENT) and not sent(pack.ui["intro"][:12]), "a repeated /start does not reset progress")
        app.store.reset(); FAIL_FOR.add(RECIPIENT)
        await app.fire_job()
        check(sent("never pressed /start", OWNER), "the owner is told the recipient never pressed /start")
        FAIL_FOR.clear()


def run():
    asyncio.run(run_pack("packs/lighthouse", "Let there be light!"))
    asyncio.run(run_pack("packs/template", "open sesame"))
    print("\nTOTAL:", "all checks passed ✅" if FAILS == 0 else f"failed checks: {FAILS} ❌")
    assert FAILS == 0


def test_flow():
    run()


if __name__ == "__main__":
    run()
