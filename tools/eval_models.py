"""Compare Ollama models on the same player moves (same prompts and checks as in the bot).

    python tools/eval_models.py --pack packs/lighthouse qwen3:8b gemma3:12b
Output: eval_results.md (replies side by side, timings, fallback rate). Judge the answers blind.
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lorequest.llm import LLM  # noqa: E402
from lorequest.pack import Pack  # noqa: E402

FALLBACK = "<<FALLBACK>>"
CUSTOM_MOVES = ["do nothing", "blow everything up", "ask politely what is going on", "run away"]


async def run_model(pack: Pack, model: str, url: str, cases):
    llm = LLM(pack, url, model)
    await llm.ping()  # warm-up: loading the model into memory must not be counted in the timings
    rows = []
    for loc, label, choice, custom in cases:
        t0 = time.time()
        prompt = pack.prompts["comment"].format(context=loc.context, choice=choice, instruction=loc.instruction,
                                                reminder=pack.prompts["reminder"])
        ai = await llm.ask([{"role": "user", "content": prompt}], fallback=FALLBACK)
        bridge = None
        if custom and loc.bridge_premise:
            bp = pack.prompts["bridge"].format(choice=choice, premise=loc.bridge_premise)
            bridge = await llm.ask([{"role": "user", "content": bp}], fallback=FALLBACK)
        rows.append((ai, bridge, time.time() - t0))
        print(f"[{model}] {loc.id} {label}: {rows[-1][2]:.1f}s{' FALLBACK' if ai == FALLBACK else ''}")
    return rows


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="packs/lighthouse")
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--custom", nargs="*", default=CUSTOM_MOVES, help="free-text moves to try")
    ap.add_argument("models", nargs="+")
    a = ap.parse_args()
    pack = Pack.load(a.pack)
    cases = []
    for loc in pack.locations:
        cases += [(loc, f"option {i}", o, False) for i, o in enumerate(loc.options, 1)]
        cases += [(loc, "custom", m, True) for m in a.custom]
    results = {m: await run_model(pack, m, a.url, cases) for m in a.models}

    lines = ["# Model comparison\n"]
    for m, rows in results.items():
        fb = sum(r[0] == FALLBACK for r in rows)
        lines.append(f"- **{m}**: fallbacks {fb}/{len(rows)}, avg {sum(r[2] for r in rows) / len(rows):.1f}s")
    lines.append("")
    for i, (loc, label, choice, _) in enumerate(cases):
        lines.append(f"## {loc.id} · {label}: «{choice}»\n")
        for m, rows in results.items():
            ai, bridge, dt = rows[i]
            lines.append(f"**{m}** ({dt:.1f}s)\n\n> {ai}\n")
            if bridge:
                lines.append(f"> 🌀 bridge: {bridge}\n")
    out = ROOT / "eval_results.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("Done:", out)


if __name__ == "__main__":
    asyncio.run(main())
