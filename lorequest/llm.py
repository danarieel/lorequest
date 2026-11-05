"""Ollama client with reply validation: the model must not break character or invent forbidden things."""
from __future__ import annotations

import asyncio
import logging
import re

import aiohttp

from .pack import Pack

log = logging.getLogger("lorequest.llm")

_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_CJK_RE = re.compile("[\u3040-\u30ff\u4e00-\u9fff]")


class LLM:
    def __init__(self, pack: Pack, base_url: str, model: str):
        self.pack = pack
        self.base = base_url.rstrip("/")
        self.model = model
        v = pack.validation
        self.required = (v.get("required_substring") or "").lower()
        self.forbidden = [re.compile(p, re.I) for p in v.get("forbidden_patterns", [])]
        self.reject_cjk = bool(v.get("reject_cjk", True))
        self.max_chars = int(v.get("max_chars", 450))
        self._no_think: set[str] = set()
        self.fewshot = []
        for pair in pack.persona.get("fewshot") or []:
            self.fewshot += [{"role": "user", "content": pair["user"]}, {"role": "assistant", "content": pair["assistant"]}]

    # ---------- server state ----------
    async def wait_ready(self, timeout: int = 90) -> bool:
        """Wait until Ollama opens its port (after a PC autostart it is not instant)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
                    async with s.get(f"{self.base}/api/tags") as r:
                        if r.status == 200:
                            return True
            except Exception:
                pass
            await asyncio.sleep(3)
        return False

    async def ping(self) -> bool:
        """Warm the model up (load it into VRAM) and check that it exists."""
        return await self._call([{"role": "user", "content": "Say one word."}], 0.7) is not None

    # ---------- requests ----------
    async def _call(self, messages: list[dict], temperature: float) -> str | None:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.pack.persona["system_prompt"]}, *self.fewshot, *messages],
            "stream": False,
            "think": False,  # no "thinking": otherwise the model deliberates for tens of seconds
            "keep_alive": "2h",  # keep the model loaded in VRAM
            "options": {"temperature": temperature, "top_p": 0.9, "repeat_penalty": 1.1,
                        "num_ctx": 4096, "num_predict": 200},
        }
        if self.model in self._no_think:
            payload.pop("think", None)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
                async with session.post(f"{self.base}/api/chat", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("message", {}).get("content", "")
                    body = await resp.text()
                    if resp.status == 400 and "think" in body.lower() and self.model not in self._no_think:
                        self._no_think.add(self.model)  # the model has no thinking mode: retry without `think`
                        log.warning("Model does not support `think`, retrying without it")
                        return await self._call(messages, temperature)
                    log.error("Ollama HTTP %s: %s", resp.status, body)
        except Exception:
            log.exception("Ollama unavailable")
        return None

    # ---------- reply checks ----------
    def clean(self, text: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        text = _EMOJI_RE.sub("", text).replace("*", "").replace("#", "")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > self.max_chars:
            cut = text[: self.max_chars]
            end = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
            text = cut[: end + 1] if end > 100 else cut
        return text

    def valid(self, text: str) -> bool:
        return (
            len(text) >= 20
            and (not self.required or self.required in text.lower())
            and not (self.reject_cjk and _CJK_RE.search(text))
            and not any(p.search(text) for p in self.forbidden)
        )

    async def ask(self, messages: list[dict], fallback: str, validate: bool = True) -> str:
        """Up to three attempts with decreasing temperature; if validation never passes, return the fallback."""
        if not validate:
            raw = await self._call(messages, 0.7)
            return self.clean(raw) if raw else fallback
        for temperature in (0.7, 0.5, 0.4):
            raw = await self._call(messages, temperature)
            if raw is None:
                break  # server unavailable: retries are pointless
            text = self.clean(raw)
            if self.valid(text):
                return text
            log.warning("Reply failed validation, retrying: %r", text[:120])
        return fallback
