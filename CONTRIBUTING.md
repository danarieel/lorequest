# Contributing

Thanks for looking! A few ground rules keep the project small and predictable.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python tests/test_pack.py && python tests/test_generator.py && python tests/flow_test.py   # must pass before you open a PR
```

The tests need neither Telegram nor Ollama (both are mocked), so they run anywhere and in CI.

## What fits well

- **New packs** (`packs/<name>/pack.yaml`): any language. Run `python bot.py --pack packs/<name>` once: the loader names every broken key.
  Keep shipped packs free of third-party art and of personal data (IDs, tokens, real names).
- **Validators and guards** in `src/lorequest/core/llm.py` (per-pack options belong in `validation:` in the pack).
- **Other LLM backends**: keep the `LLM.ask(messages, fallback, validate)` interface.
- **Docs and translations** of the README and `docs/pack-format.md`.

## Principles

- Content lives in `packs/`, behaviour in `src/lorequest/` (`core/` is the Telegram-free engine, `bot/` is the Telegram layer). If a feature needs per-quest wording, it is a pack key, not a hard-coded string.
- The model never gets to decide facts or story structure: authored text and code-attached facts first, generated text second, always validated.
- Every change that touches the turn logic needs a check in `tests/flow_test.py`.

## Commit messages

Conventional Commits, in English: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `ci:`, `chore:`
(for example `feat: add pack generator` or `fix: prefer .env over environment variables`).

## Pull requests

Small and focused, with a short description of the user-visible change. Please don't commit `.env`, `config.json` or `data/`.
