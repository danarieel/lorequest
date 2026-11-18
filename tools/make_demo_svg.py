"""Build docs/demo.svg: an animated, Telegram-style illustration of a session with a pack.

    python tools/make_demo_svg.py [--pack packs/lighthouse] [--out docs/demo.svg]

Authored text (intro, chapter text, options, verified fact) is taken from the pack, so the picture stays in sync with it.
Lines marked with a star are ILLUSTRATIVE model output: they are written here by hand and vary in real runs.
"""
import argparse
import re
import sys
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from lorequest.core.pack import Pack  # noqa: E402

W, PAD, LH, FS = 760, 28, 22, 15
BUBBLE_MAX, WRAP = 520, 56
CHAR_W = 7.6
STAR = "✦"


def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def wrap(text: str, width: int = WRAP) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        out += textwrap.wrap(para, width) or [""]
    return out


def build(pack: Pack) -> str:
    ui = pack.ui
    p1, p2 = pack.locations[0], pack.locations[1]
    speaker = pack.persona["speaker_label"]
    opt = p1.options[2]  # "Light a signal fire on the rocks."
    fact = pack.find_fact(opt, [])
    footnote = strip_tags(ui["fact_footnote"].format(fact=fact)) if fact else ""

    def chapter(loc, short=False):
        lines = [("b", strip_tags(loc.title))]
        if short:
            first = re.split(r"(?<=[.!?]) ", loc.body)[0]
            lines += [("", l) for l in wrap(first)] + [("d", "…")]
        else:
            lines += [("", l) for l in wrap(loc.body)] + [("", "")]
            lines += [("", l) for l in wrap(loc.question)]
            lines += [("", l) for l in wrap("\n".join(f"{i}. {o}" for i, o in enumerate(loc.options, 1)))]
            lines += [("", f"{loc.custom_key}. {loc.custom_label}")]
        return lines

    intro = strip_tags(ui["intro"]).split("\n")
    msgs = [  # (side, lines, chip)
        ("bot", [("b", intro[0])] + [("", l) for l in wrap(intro[1])], ui["start_button"]),
        ("user", [("", ui["start_button"])], None),
        ("bot", chapter(p1), None),
        ("user", [("", "3")], None),
        ("bot", [("", l) for l in wrap(f"🗣 {speaker}: {STAR} The Keeper has watched driftwood burn on that shore "
                                      "before, traveler. Nothing came of it but smoke.")]
         + [("", "")] + [("d", l) for l in wrap(footnote)] + [("", "")]
         + [("", ui["confirm_prompt"])], ui["next_phrases"][0]),
        ("user", [("", ui["next_phrases"][0])], None),
        ("bot", chapter(p2, short=True), None),
        ("user", [("", p2.custom_key)], None),
        ("bot", [("", p2.custom_prompt)], None),
        ("user", [("", "burn the logbook")], None),
        ("bot", [("", l) for l in wrap(f"🗣 {speaker}: {STAR} The Keeper approves of the fire and doubts the reason, "
                                      "traveler. Paper is a poor witness.")]
         + [("", "")] + [("i", l) for l in wrap(f"🌀 {STAR} The pages curl, the night tears at the seam, and the tower swallows "
                                                "the flame whole.")]
         + [("", "")] + [("", ui["confirm_prompt"])], ui["next_phrases"][2]),
    ]

    y = 84
    parts, delay = [], 0.0
    for side, lines, chip in msgs:
        longest = max(len(t) for _, t in lines)
        bw = min(BUBBLE_MAX, max(110, int(longest * CHAR_W) + 30))
        bh = len(lines) * LH + 18
        x = PAD if side == "bot" else W - PAD - bw
        fill = "#182533" if side == "bot" else "#2b5278"
        g = [f'<g class="m" style="animation-delay:{delay:.1f}s">',
             f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="14" fill="{fill}"/>']
        for i, (style, text) in enumerate(lines):
            if not text:
                continue
            attrs = {"b": ' font-weight="700"', "i": ' font-style="italic"', "d": ' fill="#8da2b8"'}.get(style, "")
            g.append(f'<text x="{x + 15}" y="{y + 25 + i * LH}"{attrs}>{escape(text)}</text>')
        y += bh
        if chip:
            cw = int(len(chip) * CHAR_W) + 30
            g.append(f'<rect x="{x}" y="{y + 8}" width="{cw}" height="30" rx="9" fill="#1f2f43" stroke="#34506e"/>'
                     f'<text x="{x + cw / 2}" y="{y + 28}" text-anchor="middle" fill="#cfe0f2">{escape(chip)}</text>')
            y += 38
        g.append("</g>")
        parts.append("\n".join(g))
        y += 14
        delay += 1.6

    note_y = y + 18
    H = note_y + 44
    total = delay + 7
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Sample session with the {escape(pack.meta["title"])} pack">
<style>
text{{font-family:-apple-system,"Segoe UI",Roboto,"Noto Sans",Helvetica,Arial,sans-serif;font-size:{FS}px;fill:#e8eef5}}
.m{{animation:show {total:.0f}s infinite both}}
@keyframes show{{0%{{opacity:0;transform:translateY(8px)}}3%{{opacity:1;transform:none}}94%{{opacity:1;transform:none}}100%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{.m{{animation:none}}}}
</style>
<rect width="{W}" height="{H}" rx="18" fill="#0e1621"/>
<rect width="{W}" height="62" rx="18" fill="#17212b"/><rect y="40" width="{W}" height="22" fill="#17212b"/>
<circle cx="44" cy="31" r="19" fill="#2b5278"/><text x="44" y="38" text-anchor="middle" style="font-size:20px">🔦</text>
<text x="76" y="28" font-weight="700">{escape(pack.meta["title"])}</text>
<text x="76" y="47" style="font-size:12px;fill:#6c7f93">bot</text>
{chr(10).join(parts)}
<text x="{W / 2}" y="{note_y}" text-anchor="middle" style="font-size:12px;fill:#6c7f93">Illustrative session. Authored text comes from packs/{escape(pack.root.name)};</text>
<text x="{W / 2}" y="{note_y + 18}" text-anchor="middle" style="font-size:12px;fill:#6c7f93">lines marked {STAR} are model output and differ from run to run.</text>
</svg>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=str(ROOT / "packs/lighthouse"))
    ap.add_argument("--out", default=str(ROOT / "docs/demo.svg"))
    a = ap.parse_args()
    svg = build(Pack.load(a.pack))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(svg, encoding="utf-8")
    print("Written:", a.out)


if __name__ == "__main__":
    main()
