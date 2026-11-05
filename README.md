# lorequest

**An engine for Telegram text quests that use a local LLM.** The plot is written in advance and lives in a YAML *lore pack*.
The model (Ollama: no cloud, no API keys) only writes the narrator's commentary, short "bridges" after free-text moves, a final
verdict and the free chat after the ending. Every model reply is cleaned and validated, so a small local model can't wander off the story.

## Features

- **Scripted plot, generated voice.** Locations and options are authored; the LLM cannot derail the story.
- **Hallucination guards.** Replies are cleaned (emoji, markdown, length) and validated (required persona word, forbidden patterns,
  no CJK noise), regenerated up to 3 times at lower temperature, then replaced by an authored fallback.
- **Verified facts attached by code.** Trivia such as etymologies comes from a list you verified; the code attaches it when a trigger
  word appears in the player's choice. The model is never asked to recall facts (small models get them wrong).
- **Free-text moves don't break the story.** After a custom move the engine writes a "bridge" that explains how even "burn the
  tower down" leads to the next authored scene.
- **Game feel.** A start button, a "continue" button with shuffled labels, an LLM verdict that quotes the player's real choices,
  easter eggs, optional cryptic `/hint`s, a secret ending, free chat after the final, progress that survives restarts.
- **Safe by default.** The bot answers only its owner unless you open it up (`access`: `owner` / `list` / `anyone`), so strangers
  can't burn your GPU.
- **Optional scheduled delivery.** Send the quest to a chosen person at a chosen time (a gift, an event, a class) with retries,
  a startup self-check (model, images, recipient ID) and alerts to you.
- **Tooling.** `tools/eval_models.py` compares models blind; an end-to-end test runs the whole quest with Telegram and the model mocked.

## How a turn works

```
player picks 1..N or a free-text move
        │
        ▼
 build prompt from the location (context, instruction, the DISPLAYED option text)
        │
        ▼
 LLM.ask ── clean ── validate ──┬─ ok ───────────────► comment (+ verified fact footnote)
        ▲                       └─ bad: retry ×3 ────► authored fallback
        │
 free-text move? ─► "bridge" explaining the way to the next scene
        │
        ▼
 "continue" button ─► next location, or verdict + final ─► free chat
```

## Sample session (abridged)

The plot lines are authored in `packs/lighthouse`; the lines marked ✦ are model output and differ from run to run.

```
Bot   🔦 [THE LAST LIGHT]  A storm. A tower. Someone is waiting, traveler.        [ Approach ]
You   Approach
Bot   🌊 CHAPTER 1: The Landing. The storm has thrown your boat onto the rocks ...
      1. Knock on the door of the lighthouse.   2. Climb the cliff path ...
      3. Light a signal fire on the rocks.      4. Describe your own plan.
You   3
Bot   ✦ The Keeper: The Keeper has watched driftwood burn on that shore before, traveler. Nothing came of it but smoke.
      📜 The Keeper recalls: «beacon» comes from Old English «bēacen», «sign, signal»      <- verified fact, added by code
      ⏳ Take in the Keeper's words, traveler.                                            [ Go on ]
You   Go on
Bot   🔦 CHAPTER 2: The Lamp Room. ...
You   4  ->  "set the logbook on fire"
Bot   ✦ The Keeper: ...
      ✦ 🌀 The burning pages tear the night open, and the tower swallows the flames.   <- "bridge" to the next scene
...
Bot   ✦ ⚖️ The Keeper's verdict: ... (refers to what you really did)
      🔦 [THE LAST LIGHT] The lamp turns, the beam sweeps the water ...  -> free chat opens
```

## Project structure

```
lorequest/
├── lorequest/            the engine (pure Python package)
│   ├── __main__.py       entry point: python -m lorequest ...
│   ├── config.py         .env + config.json + CLI flags -> Settings
│   ├── pack.py           loads and VALIDATES pack.yaml; locations, facts, easter eggs, secret ending
│   ├── llm.py            Ollama client, retries, answer cleaning and validation
│   ├── bot.py            Telegram layer: aiogram handlers, FSM, keyboards, scheduler, scheduled delivery
│   ├── store.py          saved progress (JSON) that survives restarts
│   └── ops.py            messages to the operator (en/ru)
├── packs/
│   ├── lighthouse/       demo pack: "The Last Light", a three-chapter gothic mystery
│   └── template/         commented template: copy it to start your own world
├── docs/pack-format.md   reference for every pack.yaml key
├── tests/                pack validation + an end-to-end flow test (Telegram and the model are mocked)
├── tools/eval_models.py  compare Ollama models on the same moves
├── .env.example          TELEGRAM_TOKEN, OLLAMA_MODEL
└── config.example.json   owner_id, recipient_id, launch_at, operator_language
```

Rule of thumb: **content goes in `packs/`, behaviour goes in `lorequest/`.** You should never need to edit the engine to make a new quest.

## Quick start

You need Python 3.10+, [Ollama](https://ollama.com) with a chat model, and a bot token from [@BotFather](https://t.me/BotFather).

Clone or download the repository, then:

Linux / macOS:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen3:8b
cp .env.example .env && cp config.example.json config.json
```

Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
ollama pull qwen3:8b
copy .env.example .env
copy config.example.json config.json
```

Edit `.env` (set `TELEGRAM_TOKEN`, and `OLLAMA_MODEL` to the exact name from `ollama list`) and `config.json` (set `owner_id` to your
Telegram ID; [@userinfobot](https://t.me/userinfobot) shows it). Then, **from the repository folder**:

```bash
python -m lorequest --pack packs/lighthouse
```

The bot starts and waits. Open it in Telegram and press **/start**: the quest begins. By default only the owner can talk to it
(see `access` below). Stop with `Ctrl+C`. Logs: `data/bot.log`.

## Configuration

| Where | Key | Meaning |
|---|---|---|
| `.env` | `TELEGRAM_TOKEN` | Bot token (required). |
| `.env` | `OLLAMA_MODEL`, `OLLAMA_URL` | Model name (exact, from `ollama list`) and server URL. |
| `config.json` | `owner_id` | Your Telegram ID: always allowed, receives alerts. |
| `config.json` | `access`, `allowed_ids` | Who may use the bot: `"owner"` (default), `"list"` (owner + `allowed_ids`) or `"anyone"`. |
| `config.json` | `recipient_id`, `launch_at` | Only with `--deliver`: who gets the quest and when (local machine time, ISO format). |
| `config.json` | `operator_language` | `en` or `ru` for operator alerts. |
| CLI | `--pack`, `--deliver`, `--reset`, `--config`, `--data-dir` | Pack folder, scheduled delivery, wipe saved progress, other paths. |

Precedence: `.env` in the project folder > environment variables > `config.json` > defaults. (So an old `setx TELEGRAM_TOKEN` can't override your `.env`.)

**Public bot?** Set `"access": "anyone"`. Every player gets their own saved progress; all generation runs on your machine, so size your model accordingly.

### Scheduled delivery (optional)

Everything above works with plain `/start`. If you want the bot to **write first** at a chosen time instead (a birthday greeting,
a class assignment, an event), add `--deliver`.

1. Set `recipient_id` and `launch_at` in `config.json`.
2. The recipient must press **Start** in your bot once beforehand (Telegram doesn't allow bots to message first). The bot answers that
   the door opens at the appointed hour and tells you whether their ID matches the config.
3. Run `python -m lorequest --pack packs/my_world --deliver` and wait for the "🟢 Delivery mode is running" message. It lists problems
   (missing images, model not found, wrong ID) if there are any.
4. Keep the machine, Ollama and the bot running while the recipient plays.

## Write your own world

```bash
cp -r packs/template packs/my_world      # edit packs/my_world/pack.yaml
python -m lorequest --pack packs/my_world
```

The engine validates the pack on start and names the broken key. Reference: [docs/pack-format.md](docs/pack-format.md).
Images are optional: add `image:` fields and put the files next to `pack.yaml`.

## Choosing a model

Any Ollama chat model works. Compare on your language and hardware, and read the answers blind:

```bash
python tools/eval_models.py --pack packs/lighthouse qwen3:8b gemma3:12b     # writes eval_results.md
```

In our Russian-language tests a 9B Qwen was the fastest and wittiest; a 12B Gemma was more grammatical but repetitive.
Neither could be trusted with facts, which is why facts are attached by code.

## Tests

```bash
python tests/test_pack.py      # pack validation
python tests/flow_test.py      # the whole quest end to end, Telegram and the model mocked
```

## Status and limitations

Version 0.1: it works and is tested end to end (with mocks), but it is young. Telegram long polling only, a single process, progress in a
JSON file, Ollama as the only LLM backend. Pure Python, no OS-specific code; developed on Windows with a consumer GPU.
Small local models still produce odd sentences now and then: the guards reduce this, they don't remove it.

## Roadmap

- Optional fully generative mode: the model proposes the next scene and state changes within a schema, guarded by a story skeleton.
- A rolling summary for long free chats; more validators (per-pack banned-topic lists).
- Packs in more languages; a pack linter.

## Contributing

Packs in new languages, extra validators, other LLM backends and bug reports are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Keep the bot token only in `.env` (never commit it; the repository's `.gitignore` already excludes `.env`, `config.json`, `data/`).
If a token ever reaches a public place, revoke it in @BotFather immediately.

## License

MIT. Check the license of the model you run.

Русская версия: [README.ru.md](README.ru.md)
