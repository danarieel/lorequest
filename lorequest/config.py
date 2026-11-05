"""Settings: .env + config.json + command-line flags. No code edits needed."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Settings:
    token: str
    owner_id: int
    recipient_id: int
    launch_at: datetime
    model: str
    ollama_url: str
    deliver: bool
    reset: bool
    access: str            # "owner" | "list" | "anyone"
    allowed_ids: frozenset[int]
    token_source: str
    operator_language: str
    pack_dir: Path
    data_dir: Path


def _read_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env parser (KEY=VALUE). utf-8-sig: Windows Notepad sometimes adds a BOM."""
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="lorequest", description="Telegram quest bot with a local LLM")
    p.add_argument("--pack", default="packs/lighthouse", help="folder of the lore pack (contains pack.yaml)")
    p.add_argument("--config", default="config.json", help="settings file")
    p.add_argument("--data-dir", default="data", help="where to store progress and logs")
    p.add_argument("--deliver", action="store_true", help="also deliver the quest to recipient_id at launch_at")
    p.add_argument("--reset", action="store_true", help="delete saved progress before starting")
    return p.parse_args(argv)


def load_settings(argv=None) -> Settings:
    args = parse_args(argv)
    dotenv = _read_dotenv(Path(".env"))
    cfg = {"recipient_id": 0, "launch_at": "2099-01-01T00:00:00", "operator_language": "en",
           "access": "owner", "allowed_ids": []}
    cfg_path = Path(args.config)
    if cfg_path.exists():
        cfg.update(json.loads(cfg_path.read_text(encoding="utf-8-sig")))
    # Precedence: .env in the project folder > environment variables > config.json > defaults.
    # (So a stale variable set long ago with setx cannot override the token in .env.)
    def pick(key: str):
        if dotenv.get(key):
            return dotenv[key], ".env"
        if os.environ.get(key):
            return os.environ[key], "environment variable"
        return None, ""

    token, token_source = pick("TELEGRAM_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_TOKEN is not set (put it into .env, see .env.example)")
    model, _ = pick("OLLAMA_MODEL")
    url, _ = pick("OLLAMA_URL")
    if cfg["access"] not in ("owner", "list", "anyone"):
        raise SystemExit('config.json: "access" must be "owner", "list" or "anyone"')
    if "owner_id" not in cfg:
        raise SystemExit("owner_id is missing: copy config.example.json to config.json and fill it in")
    return Settings(
        token=token,
        owner_id=int(cfg["owner_id"]),
        recipient_id=int(cfg["recipient_id"]),
        launch_at=datetime.fromisoformat(cfg["launch_at"]),
        model=model or cfg.get("model") or "qwen3:8b",
        ollama_url=(url or cfg.get("ollama_url") or "http://localhost:11434").rstrip("/"),
        deliver=args.deliver,
        reset=args.reset,
        access=cfg["access"],
        allowed_ids=frozenset(int(i) for i in cfg["allowed_ids"]),
        token_source=token_source,
        operator_language=cfg["operator_language"],
        pack_dir=Path(args.pack),
        data_dir=Path(args.data_dir),
    )
