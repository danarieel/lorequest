"""Simple JSON progress store: survives bot restarts."""
from __future__ import annotations

import json
from pathlib import Path


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def update(self, **kw):
        d = self.load()
        d.update(kw)
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    def stage(self, uid: int) -> str | None:
        return self.load().get("stages", {}).get(str(uid))

    def save_stage(self, uid: int, stage: str):
        stages = self.load().get("stages", {})
        stages[str(uid)] = stage
        self.update(stages=stages)

    def forget_user(self, uid: int):
        stages = {k: v for k, v in self.load().get("stages", {}).items() if k != str(uid)}
        self.update(stages=stages)

    def reset(self):
        if self.path.exists():
            self.path.unlink()
