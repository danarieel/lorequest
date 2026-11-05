"""Load and validate a lore pack (pack.yaml): the whole quest world is data, not code."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class PackError(ValueError):
    """A problem in pack.yaml; the message names the key to fix."""


REQUIRED = {
    "meta": ("id", "title"),
    "persona": ("system_prompt", "speaker_label"),
    "prompts": ("comment", "reminder", "bridge", "verdict"),
    "ui": (
        "intro", "start_button", "press_start", "waiting_confirm", "confirm_prompt", "confirm_prompt_final",
        "confirm_placeholder", "choice_placeholder", "unknown_command", "non_text", "not_started",
        "recipient_waiting", "resumed", "resumed_free", "hint_free", "hint_early", "hint_empty", "hint_format",
        "comment_format", "bridge_format", "fallback_reply", "next_phrases",
    ),
    "final": ("text",),
}
LOCATION_KEYS = ("id", "title", "body", "question", "options", "custom_label", "custom_prompt",
                 "context", "instruction", "fallback")


@dataclass
class Location:
    id: str
    title: str
    body: str
    question: str
    options: list[str]
    custom_label: str
    custom_prompt: str
    context: str
    instruction: str
    fallback: str
    image: str | None = None
    bridge_premise: str | None = None

    @property
    def custom_key(self) -> str:
        """Number of the free-text option (the one after the ready-made ones)."""
        return str(len(self.options) + 1)

    @property
    def option_keys(self) -> list[str]:
        return [str(i) for i in range(1, len(self.options) + 1)]

    def render(self) -> str:
        lines = [f"{i}. {o}" for i, o in enumerate(self.options, 1)]
        lines.append(f"{self.custom_key}. {self.custom_label}")
        return f"{self.title}\n{self.body}\n\n{self.question}\n" + "\n".join(lines)


def _norm(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


class Pack:
    def __init__(self, data: dict[str, Any], root: Path):
        self.root = Path(root)
        self._check(data)
        self.meta = data["meta"]
        self.persona = data["persona"]
        self.prompts = data["prompts"]
        self.ui = data["ui"]
        self.final = data["final"]
        self.validation = data.get("validation") or {}
        self.free_chat = data.get("free_chat") or {}
        self.hints = list(data.get("hints") or [])
        self.facts = [
            {"triggers": [t.lower() for t in f["triggers"]], "text": f["text"]} for f in (data.get("facts") or [])
        ]
        self.locations = [Location(**loc) for loc in data["locations"]]
        self._by_id = {loc.id: loc for loc in self.locations}
        self.eggs = [
            {
                "triggers": {_norm(t) for t in (e.get("triggers") or [])},
                "patterns": [re.compile(p, re.I) for p in (e.get("patterns") or [])],
                "reply": e["reply"],
            }
            for e in (data.get("easter_eggs") or [])
        ]
        self.secret = None
        if data.get("secret_ending"):
            s = dict(data["secret_ending"])
            s["_re"] = [re.compile(p, re.I) for p in s["patterns"]]
            self.secret = s
        self._check_semantics()

    # ---------- loading ----------
    @classmethod
    def load(cls, folder: str | Path) -> "Pack":
        folder = Path(folder)
        path = folder / "pack.yaml"
        if not path.exists():
            raise PackError(f"Not found: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise PackError(f"{path}: YAML error: {e}") from e
        if not isinstance(data, dict):
            raise PackError(f"{path}: the root must be a mapping")
        return cls(data, folder)

    # ---------- checks ----------
    @staticmethod
    def _check(data: dict[str, Any]):
        for section, keys in REQUIRED.items():
            if section not in data or not isinstance(data[section], dict):
                raise PackError(f"Missing section '{section}'")
            for k in keys:
                if k not in data[section]:
                    raise PackError(f"Section '{section}' has no key '{k}'")
        if not data["ui"]["next_phrases"]:
            raise PackError("ui.next_phrases must not be empty")
        locs = data.get("locations")
        if not isinstance(locs, list) or not locs:
            raise PackError("At least one location is required in 'locations'")
        seen = set()
        for i, loc in enumerate(locs, 1):
            for k in LOCATION_KEYS:
                if k not in loc:
                    raise PackError(f"Location #{i} has no key '{k}'")
            if loc["id"] in seen:
                raise PackError(f"Duplicate location id: {loc['id']}")
            seen.add(loc["id"])
            if not 2 <= len(loc["options"]) <= 5:
                raise PackError(f"Location {loc['id']}: it needs 2 to 5 ready-made options")
        for i, f in enumerate(data.get("facts") or [], 1):
            if "text" not in f or not f.get("triggers"):
                raise PackError(f"facts #{i}: 'text' and a non-empty 'triggers' are required")
        for i, e in enumerate(data.get("easter_eggs") or [], 1):
            if "reply" not in e or not (e.get("triggers") or e.get("patterns")):
                raise PackError(f"easter_eggs #{i}: 'reply' and 'triggers' or 'patterns' are required")
        if data.get("secret_ending"):
            for k in ("location", "patterns", "text"):
                if k not in data["secret_ending"]:
                    raise PackError(f"'secret_ending' has no key '{k}'")
        if data["ui"].get("fact_footnote") is None and data.get("facts"):
            raise PackError("'facts' are defined but ui.fact_footnote is missing")

    def _check_semantics(self):
        if self.secret and self.secret["location"] not in self._by_id:
            raise PackError(f"secret_ending.location: no such location '{self.secret['location']}'")
        for loc in self.locations[:-1]:
            if not loc.bridge_premise:
                raise PackError(f"Location {loc.id}: bridge_premise is required (a description of the next scene)")
        for p in self.validation.get("forbidden_patterns", []):
            re.compile(p)

    # ---------- navigation ----------
    @property
    def first(self) -> Location:
        return self.locations[0]

    def loc(self, loc_id: str) -> Location:
        return self._by_id[loc_id]

    def index(self, loc_id: str) -> int:
        return self.locations.index(self._by_id[loc_id])

    def next_id(self, loc_id: str) -> str:
        """Id of the next location, or 'final' after the last one."""
        i = self.index(loc_id) + 1
        return self.locations[i].id if i < len(self.locations) else "final"

    def image_path(self, name: str | None) -> Path | None:
        return (self.root / name) if name else None

    def required_images(self) -> list[str]:
        names = [loc.image for loc in self.locations if loc.image] + ([self.final["image"]] if self.final.get("image") else [])
        return names

    def optional_images(self) -> list[str]:
        return [self.secret["image"]] if self.secret and self.secret.get("image") else []

    # ---------- content ----------
    def find_fact(self, choice: str, used: list[str]) -> str | None:
        """A verified fact for the words in the player's choice (None if nothing matches)."""
        low = choice.lower()
        hits = [f["text"] for f in self.facts if any(t in low for t in f["triggers"])]
        if not hits:
            return None
        fresh = [h for h in hits if h not in used] or hits
        pick = random.choice(fresh)
        used.append(pick)
        if len(used) >= len(self.facts):
            used.clear()
        return pick

    def is_secret(self, text: str) -> bool:
        return bool(self.secret and any(r.match(text.strip()) for r in self.secret["_re"]))

    def find_egg(self, text: str, stage_id: str | None = None) -> str | None:
        """Reply to an easter egg. stage_id=None means the player is already in free chat."""
        t = text.strip()
        if self.is_secret(t):  # on the secret location itself this is not reached: the engine intercepts it earlier
            if stage_id is not None and self.index(stage_id) < self.index(self.secret["location"]):
                return self.secret.get("early_reply")
            return self.secret.get("late_reply")
        n = _norm(t)
        for e in self.eggs:
            if n in e["triggers"] or any(p.match(t) for p in e["patterns"]):
                return e["reply"]
        return None
