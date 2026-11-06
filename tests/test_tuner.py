"""The tuner page (docs/tune) keeps its own copy of her bars, ends and side names, since a static page cannot import
Python: they must stay those of mneme_llm.gut. Its star map (starmap.js) lives her birth again from her starter and
reads her heart as gut.py does: run in node, where node is, it must give what gut.py gives. And her settings page there
changes her files (tune.js `settle`) as Python would: with node and sql.js (`npm install sql.js@1.10.3`, or MNEME_SQLJS
naming its sql-wasm.js), what it writes Python must read back as it was meant."""

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import mneme_llm
import mneme_llm.gut as G

TUNE = Path(__file__).resolve().parents[1] / "docs" / "tune" / "tune.js"
STARMAP = TUNE.with_name("starmap.js")
NODE = shutil.which("node")
ROOT = TUNE.parents[2]


def sqljs() -> str | None:
    """sql.js's sql-wasm.js for node: MNEME_SQLJS, or the one npm put beside this copy; None without either."""
    given = os.environ.get("MNEME_SQLJS")
    if given:
        return given if Path(given).is_file() else None
    if not NODE:
        return None
    found = subprocess.run([NODE, "-e", "console.log(require.resolve('sql.js'))"], capture_output=True,
                           encoding="utf-8", cwd=ROOT, timeout=60)
    return found.stdout.strip() if found.returncode == 0 else None


# Her settings page's save, in node: her files opened, a save refused (nothing written), a save made, the files written
# back. What it shows before is printed.
SETTLE = """
const fs = require('fs')
const [sqljs, tune, folder] = process.argv.slice(1)
const T = require(tune)
require(sqljs)().then(async SQL => {
  const read = name => T.open(SQL, fs.readFileSync(folder + '/' + name)).db
  const files = { gut: read('gut.db'), memory: read('her.db'), space: 'her' }
  const view = await T.settingsView(files)
  const refused = []
  for (const save of JSON.parse(process.env.REFUSED)) {
    const before = [files.memory.export(), files.gut.export()]
    try {
      await T.settle(files, save)
      refused.push(null)
    } catch (error) {
      const after = [files.memory.export(), files.gut.export()]
      refused.push([error.code, after.every((bytes, at) => Buffer.from(bytes).equals(Buffer.from(before[at])))])
    }
  }
  await T.settle(files, JSON.parse(process.env.SAVE))
  fs.writeFileSync(folder + '/her.db', files.memory.export())
  fs.writeFileSync(folder + '/gut.db', files.gut.export())
  console.log(JSON.stringify({ view, refused }))
})
"""

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
                                     encoding="utf-8", timeout=60, check=True).stdout
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

    @unittest.skipUnless(TUNE.is_file() and sqljs(), "no node with sql.js (npm install sql.js@1.10.3, or MNEME_SQLJS)")
    def test_her_settings_page_changes_her_files_as_python_reads_them(self):
        with tempfile.TemporaryDirectory() as folder:
            memory = mneme_llm.Mneme(str(Path(folder, "her.db")), "her", embed=False)
            memory.relate("u:1", "creator")
            memory.relate("u:2", "friend", closeness=60)
            memory.relate("u:3", "acquaintance")
            memory.surface.set_card("u:1", "You are her.")
            memory.close()
            gut = G.Gut(str(Path(folder, "gut.db")))
            gut.wake()
            gut.write_side("傲娇", "你嘴硬心软。", 3)
            gut.close()
            refused = [{"her": {"zone": "Mars/Olympus"}}, {"memory": {"surface_days": 0}},
                       {"people": [{"subject": "u:2", "role": "creator"}]}, {"gut": {"tune": [{"end": "sad", "nature": 7}]}},
                       {"her": {"zone": "UTC+9"}, "gut": {"side": {"name": "多疑"}}}, {"start": "deep"}]
            save = {"her": {"name": "鲸酱", "zone": "UTC+8", "card": {"text": "You are 鲸酱.", "on": True}},
                    "people": [{"subject": "u:2", "role": "family", "closeness": 85, "hold": True,
                                "tune": [{"end": "trusting", "nature": 4}]}, {"subject": "u:3", "role": ""}],
                    "memory": {"surface_days": 9, "said_words": .5}, "rows": {"liking": 12, "fade_days": 40},
                    "gut": {"tau": 300, "sensitivity": .2, "tune": [{"end": "sad", "nature": -2}],
                            "sides": [{"name": "傲娇", "weight": 5}, {"name": "多疑", "what": "你总觉得别人话里有话。"}],
                            "side": {"name": "多疑", "often": .5}}}
            done = subprocess.run([NODE, "-e", SETTLE, sqljs(), str(TUNE), folder], capture_output=True,
                                  encoding="utf-8", timeout=120, env={**os.environ, "REFUSED": json.dumps(refused),
                                                    "SAVE": json.dumps(save)})  # (ASCII: any locale)
            self.assertEqual(done.returncode, 0, done.stderr)
            page = json.loads(done.stdout)
            view = page["view"]
            self.assertEqual((view["you"], view["her"]["zone"], view["her"]["card"]),
                             ("u:1", "", {"text": "You are her.", "on": False, "how": "set"}))
            self.assertEqual([(item["subject"], item["role"], item["you"]) for item in view["people"]],
                             [("u:1", "creator", True), ("u:2", "friend", False), ("u:3", "acquaintance", False)])
            self.assertEqual((view["memory"]["surface_days"], view["memory"]["said_words"], view["me"], view["starts"]),
                             (30, .25, None, []))
            self.assertEqual([(side["name"], side["own"]) for side in view["gut"]["sides"]], [("傲娇", 3)])
            self.assertEqual(page["refused"], [["zone", True], ["memoryValue", True], ["unique", True], ["nature", True],
                                               ["notSide", True], ["part", True]])  # (and nothing of them written)
            memory = mneme_llm.Mneme(str(Path(folder, "her.db")), "her", embed=False)
            try:
                own = memory.config
                self.assertEqual((own.get("companion.name"), own.get("companion.zone"), memory.surface.span,
                                  memory.said_words, memory.relations.liking, memory.relations.fade_days),
                                 ("鲸酱", "UTC+8", 9, .5, 12, 40))
                self.assertEqual([(item.subject, item.role, round(item.closeness)) for item in memory.relations.all()],
                                 [("u:1", "creator", 100), ("u:2", "family", 85)])
                self.assertEqual(memory.relations.locks(), {"u:2": 85})
                card = memory.surface.card("u:1")
                self.assertEqual((card.text, card.on, card.by_command), ("You are 鲸酱.", True, True))
            finally:
                memory.close()
            gut = G.Gut(str(Path(folder, "gut.db")))
            try:
                gut.wake()
                self.assertEqual((gut.net.tau, gut.settings["sensitivity"], gut.settings["nudge"]), (300, .2, {"sad": -2}))
                self.assertEqual(gut.settings["people"], {"u:2": {"nudge": {"trusting": 4}}})
                self.assertEqual(gut.settings["side"], {"name": "多疑", "often": .5})
                self.assertEqual((dict(gut.grown), dict(gut.weights)),
                                 ({"傲娇": "你嘴硬心软。", "多疑": "你总觉得别人话里有话。"}, {"傲娇": 5, "多疑": 6}))
            finally:
                gut.close()


if __name__ == "__main__":
    unittest.main()
