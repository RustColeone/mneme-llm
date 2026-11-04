"""The tuner page (docs/tune) keeps its own copy of her bars, ends and side names, since a static page cannot import
Python: they must stay those of mneme_llm.gut. Its star map (starmap.js) lives her birth again from her starter and
reads her heart as gut.py does: run in node, where node is, it must give what gut.py gives."""

import ast
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import mneme_llm.gut as G

TUNE = Path(__file__).resolve().parents[1] / "docs" / "tune" / "tune.js"
STARMAP = TUNE.with_name("starmap.js")
NODE = shutil.which("node")

# Her born lessons, odd ones too: a reading with lists, one bare value, numbers and true in it, nothing at all, an old
# one-word feel ("none" is calm), a closeness in each band.
ROWS = [
    [{"people": ["mum", "a friend"], "topic": "rain", "sender_feels": " Tired "}, {"warm": 0, "sweet": .8, "sad": .2}, 2, 85],
    [{"topic": ["Exam", 3], "event": True, "toward_you": "teasing"}, "none", -1, 40],
    [{"gender": None, "topic": []}, "worried", 0, 10],
    [{"people": "her brother", "topic": "games", "event": "won"}, {"proud": 1, "cheeky": .5, "jealous": .3}, -3, 60],
    [{"sender_feels": "angry", "toward_you": "blaming"}, {"wronged": .9, "defiant": .6, "hysterical": .2}, -2, 30],
]


def literal(source: str, name: str):
    """A `const NAME = [...]` array of the page, read as a Python literal (its strings are single-quoted)."""
    start = source.index(f"const {name} = [")
    depth, at = 0, source.index("[", start)
    for end in range(at, len(source)):
        depth += {"[": 1, "]": -1}.get(source[end], 0)
        if depth == 0:
            break
    return ast.literal_eval(re.sub(r"\bnull\b", "None", source[at:end + 1]))


@unittest.skipUnless(TUNE.is_file(), "the tuner page is not in this copy")
class TunerPageTests(unittest.TestCase):
    def test_the_page_knows_her_bars_and_side_names(self):
        source = TUNE.read_text(encoding="utf-8")
        bars = [(bar, zh, tuple(left) if left else None, tuple(right)) for bar, zh, left, right in literal(source, "BARS")]
        self.assertEqual(tuple(bars), G.BARS)
        self.assertEqual(tuple(literal(source, "NAMES")), G.NAMES)


    @unittest.skipUnless(NODE and STARMAP.is_file(), "no node, or the star map is not in this copy")
    def test_the_page_lives_her_birth_as_python_does(self):
        script = (f"const S = require({json.dumps(str(STARMAP))}); const rows = {json.dumps(ROWS)};"
                  "const known = process.argv[1] === 'old' ? S.OLD : undefined;"
                  f"const heart = S.born({{ rows, known: known || {json.dumps(list(G.ENDS))} }});"
                  "const probe = rows.map(([form, , , closeness]) => [form, closeness]);"
                  "console.log(JSON.stringify({ w: Object.fromEntries(heart.w), b: heart.b,"
                  " features: rows.map(([form, , , closeness]) => S.features(form, closeness)),"
                  " strengths: S.strengths(heart, probe) }))")
        for known in (G.ENDS, G.OLD):
            with self.subTest(ends=len(known)):
                out = subprocess.run([NODE, "-e", script, "old" if known == G.OLD else "all"], capture_output=True,
                                     text=True, timeout=60, check=True).stdout
                page = json.loads(out)
                rows = [(form, feel if isinstance(feel, dict) else {"calm" if feel == "none" else feel: 1.0}, mood,
                         closeness) for form, feel, mood, closeness in ROWS]
                net = G.Net()
                net.start(rows, known)
                self.assertEqual(sorted(page["w"]), sorted(net.heart.w))
                for key, row in net.heart.w.items():
                    for mine, theirs in zip(row, page["w"][key]):
                        self.assertAlmostEqual(mine, theirs, places=12, msg=key)
                for mine, theirs in zip(net.heart.b, page["b"]):
                    self.assertAlmostEqual(mine, theirs, places=12)
                for (form, _, _, closeness), theirs in zip(ROWS, page["features"]):
                    self.assertEqual(list(G.features(form, closeness).items()), list(theirs.items()))
                strengths = [sum(net.heart.strengths(G.features(form, closeness))[k] for form, _, _, closeness in ROWS)
                             / len(ROWS) for k in range(len(G.ENDS))]
                for mine, theirs in zip(strengths, page["strengths"]):
                    self.assertAlmostEqual(mine, theirs, places=12)


if __name__ == "__main__":
    unittest.main()
