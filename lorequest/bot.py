"""Telegram layer: aiogram handlers, FSM, keyboards, scheduled delivery."""
from __future__ import annotations

import asyncio
import html
import logging
import random
from datetime import datetime, timezone

from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.chat_action import ChatActionSender
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Settings
from .llm import LLM
from .ops import t
from .pack import Location, Pack
from .store import Store

log = logging.getLogger("lorequest")
FREE = "free"


class Q(StatesGroup):
    playing = State()
    free = State()


class AccessMiddleware(BaseMiddleware):
    """Lets in only allowed users (see QuestApp.is_allowed) and drops stale /start commands."""

    def __init__(self, app: "QuestApp"):
        self.app = app

    async def __call__(self, handler, event, data):
        uid = event.from_user.id if event.from_user else None
        if not self.app.is_allowed(uid):
            log.info("Ignoring message from %s (not allowed)", uid)
            return None
        if event.text and event.text.startswith("/start") and event.date:
            age = (datetime.now(timezone.utc) - event.date).total_seconds()
            if age > 900:  # a /start queued during downtime must not start a quest retroactively
                log.info("Ignoring stale /start (%.0f s)", age)
                return None
        return await handler(event, data)


class QuestApp:
    def __init__(self, pack: Pack, settings: Settings, store: Store, llm: LLM, bot: Bot | None = None):
        self.pack, self.s, self.store, self.llm = pack, settings, store, llm
        self.ui = pack.ui
        self.bot = bot or Bot(token=settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher()
        self.scheduler = AsyncIOScheduler()
        self.history: dict[int, list[dict]] = {}
        self.used_facts: list[str] = []
        self._bag: list[str] = []
        self._last_phrase: str | None = None
        self.dp.message.outer_middleware(AccessMiddleware(self))
        self._register()

    def is_allowed(self, uid: int | None) -> bool:
        """Who may use the bot: owner (default), list (owner + allowed_ids) or anyone."""
        s = self.s
        if uid is None:
            return False
        if s.access == "anyone" or uid == s.owner_id:
            return True
        if s.deliver and uid == s.recipient_id:
            return True  # the delivery recipient always needs access
        return s.access == "list" and uid in s.allowed_ids

    # ---------- keyboards ----------
    def kb_choices(self, loc: Location) -> ReplyKeyboardMarkup:
        row = [KeyboardButton(text=str(i)) for i in range(1, len(loc.options) + 2)]
        return ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True, one_time_keyboard=False,
                                   input_field_placeholder=self.ui["choice_placeholder"])

    def kb_start(self) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=self.ui["start_button"])]],
                                   resize_keyboard=True, one_time_keyboard=True)

    def next_phrase(self) -> str:
        """A shuffled bag of phrases: each is used once per round and never twice in a row across rounds."""
        if not self._bag:
            self._bag = list(self.ui["next_phrases"])
            random.shuffle(self._bag)
            if len(self._bag) > 1 and self._bag[-1] == self._last_phrase:
                self._bag[0], self._bag[-1] = self._bag[-1], self._bag[0]
        self._last_phrase = self._bag.pop()
        return self._last_phrase

    def kb_next(self) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=self.next_phrase())]], resize_keyboard=True,
                                   one_time_keyboard=True, input_field_placeholder=self.ui["confirm_placeholder"])

    # ---------- stages ----------
    async def enter_stage(self, state: FSMContext, uid: int, stage: str):
        if stage == FREE:
            await state.set_state(Q.free)
        else:
            await state.set_state(Q.playing)
            await state.update_data(stage=stage)
        self.store.save_stage(uid, stage)

    async def begin(self, chat_id: int, state: FSMContext):
        self.history.pop(chat_id, None)
        await self.enter_stage(state, chat_id, self.pack.first.id)
        await state.update_data(custom=False, started=False, next_action=None, choices=[], hint_level=0, secret=False)
        await self.bot.send_message(chat_id, self.ui["intro"], reply_markup=self.kb_start())

    async def launch(self, chat_id: int):
        ctx = self.dp.fsm.resolve_context(self.bot, chat_id, chat_id)
        await self.begin(chat_id, ctx)
        if self.s.deliver:  # only scheduled delivery marks the quest as sent
            self.store.update(launched=True)

    async def send_image(self, chat_id: int, name: str | None):
        """Send an image from the pack folder; a missing file is simply skipped."""
        if not name:
            return
        path = self.pack.image_path(name)
        if path and path.exists():
            try:
                await self.bot.send_photo(chat_id, photo=FSInputFile(path))
            except Exception:
                log.exception("Could not send %s", path)
        else:
            log.warning("No image %s, sending text only", path)

    async def send_location(self, chat_id: int, loc: Location):
        await self.send_image(chat_id, loc.image)
        await self.bot.send_message(chat_id, loc.render(), reply_markup=self.kb_choices(loc))

    async def make_verdict(self, chat_id: int, choices: list[str]) -> str:
        if len(choices) < 2 or not self.pack.final.get("verdict", {}).get("enabled", True):
            return ""
        steps = "\n".join(f"{i}) {c}" for i, c in enumerate(choices, 1))
        prompt = self.pack.prompts["verdict"].format(steps=steps)
        async with ChatActionSender.typing(bot=self.bot, chat_id=chat_id):
            return await self.llm.ask([{"role": "user", "content": prompt}], fallback="")

    async def advance(self, chat_id: int, state: FSMContext, action: str):
        """Go to the next location (action is its id) or to the final (action == 'final')."""
        await state.update_data(next_action=None, custom=False)
        if action != "final":
            await self.enter_stage(state, chat_id, action)
            await self.send_location(chat_id, self.pack.loc(action))
            return
        data = await state.get_data()
        secret = data.get("secret", False)
        if not secret:
            verdict = await self.make_verdict(chat_id, data.get("choices", []))
            if verdict:
                fmt = self.pack.final.get("verdict", {}).get("format", "⚖️ <i>{verdict}</i>")
                await self.bot.send_message(chat_id, fmt.format(verdict=html.escape(verdict)),
                                            reply_markup=ReplyKeyboardRemove())
                await asyncio.sleep(3)
        await self.send_image(chat_id, self.pack.final.get("image"))
        prefix = (self.pack.secret.get("final_prefix", "") if secret and self.pack.secret else "")
        await self.bot.send_message(chat_id, prefix + self.pack.final["text"], reply_markup=ReplyKeyboardRemove())
        await self.enter_stage(state, chat_id, FREE)

    async def resume(self, chat_id: int, state: FSMContext, stage: str, pressed_next: bool = False):
        """Return the player to the saved stage (after a bot restart or a repeated /start)."""
        if stage == FREE or stage not in {loc.id for loc in self.pack.locations}:
            await self.enter_stage(state, chat_id, FREE)
            await self.bot.send_message(chat_id, self.ui["resumed_free"])
            return
        await self.enter_stage(state, chat_id, stage)
        await state.update_data(custom=False, started=True, next_action=None)
        if pressed_next:  # the player pressed "continue" after the restart
            await self.advance(chat_id, state, self.pack.next_id(stage))
        else:
            await self.bot.send_message(chat_id, self.ui["resumed"])
            await self.send_location(chat_id, self.pack.loc(stage))

    # ---------- the main turn ----------
    async def on_choice(self, message: types.Message, state: FSMContext):
        data = await state.get_data()
        loc = self.pack.loc(data["stage"])
        raw = message.text.strip()[:300]  # limit: long input must not bloat the model context
        chat_id = message.chat.id
        ui, pack = self.ui, self.pack

        # the secret ending, on its own location
        if pack.secret and loc.id == pack.secret["location"] and not data.get("next_action") and pack.is_secret(raw):
            await state.update_data(secret=True, custom=False, choices=[*data.get("choices", []), raw])
            await self.send_image(chat_id, pack.secret.get("image"))
            await message.answer(pack.secret["text"], reply_markup=ReplyKeyboardRemove())
            await asyncio.sleep(4)
            await self.advance(chat_id, state, "final")
            return

        egg = pack.find_egg(raw, loc.id)
        if egg:
            await message.answer(egg)
            return

        if raw == ui["start_button"]:  # the start button (works once)
            if loc.id == pack.first.id and not data.get("started"):
                await state.update_data(started=True)
                await self.send_location(chat_id, loc)
            return
        if loc.id == pack.first.id and not data.get("started"):
            await message.answer(ui["press_start"], reply_markup=self.kb_start())
            return
        if data.get("next_action"):  # waiting for the "continue" button: no further moves accepted
            await message.answer(ui["waiting_confirm"], reply_markup=self.kb_next())
            return

        custom_mode = data.get("custom", False)
        if custom_mode and raw in loc.option_keys:
            custom_mode = False  # changed their mind and picked a ready-made option
        if raw == loc.custom_key:
            await state.update_data(custom=True)
            await message.answer(loc.custom_prompt)
            return

        is_custom = custom_mode or raw not in loc.option_keys
        choice = (raw if is_custom else loc.options[int(raw) - 1]).replace("«", "").replace("»", "")
        await state.update_data(custom=False, choices=[*data.get("choices", []), choice[:120]])

        prompt = pack.prompts["comment"].format(
            context=loc.context, choice=choice, instruction=loc.instruction, reminder=pack.prompts["reminder"])
        async with ChatActionSender.typing(bot=self.bot, chat_id=chat_id):
            ai = await self.llm.ask([{"role": "user", "content": prompt}], fallback=loc.fallback)
        text = ui["comment_format"].format(speaker=pack.persona["speaker_label"], text=html.escape(ai))
        fact = pack.find_fact(choice, self.used_facts)
        if fact:
            text += "\n\n" + ui["fact_footnote"].format(fact=html.escape(fact))
        await message.answer(text)
        await asyncio.sleep(2)

        # a free-text move may break the logic (an explosion, doing nothing): the bridge explains the way to the next scene
        if is_custom and loc.bridge_premise:
            bridge_prompt = pack.prompts["bridge"].format(choice=choice, premise=loc.bridge_premise)
            async with ChatActionSender.typing(bot=self.bot, chat_id=chat_id):
                bridge = await self.llm.ask([{"role": "user", "content": bridge_prompt}], fallback="")
            if bridge:
                await message.answer(ui["bridge_format"].format(text=html.escape(bridge)))
                await asyncio.sleep(2)

        nxt = pack.next_id(loc.id)
        await state.update_data(next_action=nxt)
        prompt_key = "confirm_prompt_final" if nxt == "final" else "confirm_prompt"
        await message.answer(ui[prompt_key], reply_markup=self.kb_next())

    async def give_hint(self, message: types.Message, state: FSMContext):
        level = (await state.get_data()).get("hint_level", 0)
        if level >= len(self.pack.hints):
            await message.answer(self.ui["hint_empty"])
            return
        await state.update_data(hint_level=level + 1)
        await message.answer(self.ui["hint_format"].format(text=html.escape(self.pack.hints[level])))

    async def on_free_chat(self, message: types.Message):
        text = message.text.strip()[:600]
        egg = self.pack.find_egg(text, None)
        if egg:
            await message.answer(egg)
            return
        hist = self.history.setdefault(message.chat.id, [])
        hist.append({"role": "user", "content": text})
        recent = [dict(m) for m in hist[-8:]]
        recent[-1]["content"] += "\n" + (self.pack.free_chat.get("prompt") or "")  # the instruction goes into the request only, not into the history
        async with ChatActionSender.typing(bot=self.bot, chat_id=message.chat.id):
            ai = await self.llm.ask(recent, fallback=self.ui["fallback_reply"], validate=False)
        hist.append({"role": "assistant", "content": ai})
        await message.answer(html.escape(ai))

    # ---------- handlers ----------
    def _register(self):
        dp, ui = self.dp, self.ui

        @dp.message(Command("start"))
        async def start_cmd(message: types.Message, state: FSMContext):
            uid, s = message.from_user.id, self.s
            # delivery mode, recipient: before launch time we only acknowledge; afterwards we never reset a running quest
            # (Telegram does not let a bot message someone who never pressed Start)
            if s.deliver and uid == s.recipient_id and uid != s.owner_id:
                if datetime.now() < s.launch_at:
                    verdict = t(s.operator_language, "id_match" if uid == s.recipient_id else "id_mismatch")
                    await self.notify_owner(t(s.operator_language, "recipient_started", uid=uid,
                                              configured=s.recipient_id, verdict=verdict))
                    await message.answer(ui["recipient_waiting"])
                    return
                stage = self.store.stage(uid)
                if stage:
                    await self.resume(message.chat.id, state, stage)
                    return
            await state.clear()
            await self.begin(message.chat.id, state)

        @dp.message(Command("hint"))
        async def hint_cmd(message: types.Message, state: FSMContext):
            cur = await state.get_state()
            if cur == Q.playing.state:
                await self.give_hint(message, state)
            elif cur == Q.free.state:
                await message.answer(ui["hint_free"])
            else:
                await message.answer(ui["hint_early"])

        @dp.message(Q.playing, F.text)
        async def playing(message: types.Message, state: FSMContext):
            if message.text.startswith("/"):  # commands inside the quest are not player moves
                await message.answer(ui["unknown_command"])
                return
            if message.text in ui["next_phrases"]:  # the "continue" button: move on
                action = (await state.get_data()).get("next_action")
                if action:
                    await self.advance(message.chat.id, state, action)
                return
            await self.on_choice(message, state)

        @dp.message(Q.free, F.text)
        async def free(message: types.Message):
            await self.on_free_chat(message)

        @dp.message(StateFilter(None), F.text)
        async def restore(message: types.Message, state: FSMContext):
            # state lost (bot restart): restore it from the saved file
            stage = self.store.stage(message.chat.id)
            if not stage:
                await message.answer(ui["not_started"])
                return
            await self.resume(message.chat.id, state, stage, pressed_next=message.text in ui["next_phrases"])

        @dp.message(~F.text)
        async def non_text(message: types.Message):
            await message.answer(ui["non_text"])

    # ---------- operator and scheduling ----------
    async def notify_owner(self, text: str):
        try:
            await self.bot.send_message(self.s.owner_id, text)
        except Exception:
            log.exception("Could not notify the owner")

    async def fire_job(self):
        s, lang = self.s, self.s.operator_language
        pid = s.recipient_id
        if not pid or pid == s.owner_id:
            await self.notify_owner(t(lang, "no_recipient"))
            return
        if self.store.load().get("launched"):
            log.info("Quest was already sent, nothing to do")
            return
        for attempt in range(1, 7):
            try:
                await self.launch(pid)
                await self.notify_owner(t(lang, "sent_ok"))
                return
            except Exception as e:
                log.exception("Sending the quest, attempt %s", attempt)
                err = str(e).lower()
                if "forbidden" in err or "chat not found" in err:
                    await self.notify_owner(t(lang, "forbidden"))
                    return
                await asyncio.sleep(30)
        await self.notify_owner(t(lang, "failed"))

    async def run(self):
        try:
            await self._run()
        finally:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            await self.bot.session.close()

    async def check_token(self):
        """Find out which bot we run as; a bad token gives a clear error instead of a traceback."""
        s = self.s
        try:
            me = await self.bot.get_me()
        except TelegramUnauthorizedError:
            raise SystemExit(t(s.operator_language, "token_rejected", source=s.token_source,
                               bot_id=s.token.split(":")[0]))
        except Exception:
            log.warning("Could not reach Telegram to verify the token (network/VPN?); will keep retrying")
            return
        log.info("Telegram bot: @%s (id %s), token from %s", me.username, me.id, s.token_source)

    async def _run(self):
        s, lang, pack = self.s, self.s.operator_language, self.pack
        await self.check_token()
        if s.reset:
            self.store.reset()
            log.info("Saved progress removed (--reset)")
        model_ok = await self.llm.wait_ready() and await self.llm.ping()
        if not model_ok:
            log.error("Ollama is not responding or the model is not found: %s", s.model)
            await self.notify_owner(t(lang, "model_down", model=s.model))

        if not s.deliver:
            log.info("SERVE mode (access: %s). Open the bot in Telegram and press /start.", s.access)
        else:
            log.info("DELIVER mode: launch at %s, recipient %s", s.launch_at, s.recipient_id)
            need = pack.required_images()
            missing = [n for n in need if not (pack.root / n).exists()]
            problems = []
            if s.recipient_id in (0, s.owner_id):
                problems.append(t(lang, "p_recipient"))
            if not model_ok:
                problems.append(t(lang, "p_model"))
            if missing:
                problems.append(t(lang, "p_images", names=", ".join(missing)))
            common = dict(when=f"{s.launch_at:%Y-%m-%d %H:%M}", recipient=s.recipient_id, model=s.model)
            if problems:
                await self.notify_owner(t(lang, "deliver_problem", problems="; ".join(problems), **common))
            else:
                await self.notify_owner(t(lang, "deliver_ok", have=len(need) - len(missing), need=len(need), **common))
            self.scheduler.start()
            if datetime.now() < s.launch_at:
                # nothing can be "already sent" before launch time: clean traces of old test runs
                self.store.forget_user(s.recipient_id)
                self.store.update(launched=False)
                self.scheduler.add_job(self.fire_job, "date", run_date=s.launch_at, misfire_grace_time=6 * 3600)
            elif not self.store.load().get("launched"):
                await self.fire_job()  # the bot was started after launch time and the quest never went out

        # in normal mode messages queued during downtime are dropped; in delivery mode they are processed
        await self.dp.start_polling(self.bot, drop_pending_updates=not s.deliver)
