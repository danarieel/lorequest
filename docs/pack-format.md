# Pack format (`pack.yaml`)

A pack is one folder with `pack.yaml` and (optionally) images. The engine validates it on start
(`python -m lorequest --pack <folder>`) and refuses to run with a message that names the broken key.
Start from `packs/template/pack.yaml`: every key is commented there.

| Section | Purpose |
|---|---|
| `meta` | `id`, `title`, `language`, `description`. |
| `persona` | `speaker_label` (shown before the model's comments), `system_prompt`, `fewshot` (list of `{user, assistant}` voice examples). |
| `prompts` | Templates. `comment`: `{context} {choice} {instruction} {reminder}`. `bridge`: `{choice} {premise}`. `verdict`: `{steps}`. `reminder`: appended to every request. |
| `ui` | Every string the engine can show the player (so the whole bot stays in the persona's voice). `next_phrases` are shuffled labels for the "continue" button. |
| `locations` | Ordered list. Each: `id`, `title`, `body`, `question`, 2-5 `options`, `custom_label`, `custom_prompt`, `context`, `instruction`, `fallback`, optional `image`; every location except the last needs `bridge_premise`. |
| `facts` | Verified trivia: `{triggers: [...], text}`. The **code** attaches a fact when a trigger occurs in the player's choice, so the model never has to recall trivia (see `ui.fact_footnote`). |
| `easter_eggs` | `{triggers: [...] and/or patterns: [regex], reply}`. They cost no move and work anywhere. |
| `hints` | Optional `/hint` texts (only while the story runs, from subtle to direct). |
| `secret_ending` | Optional. `location`, `patterns` (regex), `early_reply`, `late_reply`, `image`, `text`, `final_prefix`. |
| `final` | `text`, optional `image`, `verdict: {enabled, format}` (LLM verdict that refers to the player's real choices). |
| `free_chat` | `prompt`: appended to free-chat requests after the final. |
| `validation` | `required_substring` (every scripted reply must contain it), `forbidden_patterns` (regex; replies matching them are regenerated), `reject_cjk`, `max_chars`. |

## How a turn works

1. The player picks option `1..N` or the last number for a free-text move.
2. The engine builds the `comment` prompt from the location's `context`/`instruction` and the **displayed** option text
   (options are rendered from the same list, so screen and model can never disagree).
3. `LLM.ask` generates, cleans the reply (emoji, markdown, length) and validates it (`validation`). Up to three attempts with lower
   temperature, then the location's `fallback` text is used. Nothing broken ever reaches the player.
4. For a free-text move the `bridge` prompt explains how the action leads to the next scene (`bridge_premise`).
5. A verified `fact` is appended by the code if a trigger matches.
6. The player presses a "continue" button, the next location (or the final) is sent.

## Tips for small local models

- Give 2-3 `fewshot` examples; they steer style better than any description.
- Keep prompts short, state the length limit, and list the names the model may use.
- Make the rule you care about checkable in `validation` instead of hoping the model obeys.
- Test with `python tools/eval_models.py --pack <folder> modelA modelB` and read the answers blind.
