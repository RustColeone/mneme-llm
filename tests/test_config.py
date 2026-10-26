import contextlib
import io
import json
import os
import tempfile
import tomllib
import unittest
from datetime import timedelta

from mneme_llm import STORED, Mneme
from mneme_llm import config as configs
from mneme_llm.cli import main
from mneme_llm.config import DEFAULTS, Config, check, load, to_toml
from mneme_llm.prompts import PROMPTS
from tests.invariants import check as sound

try:  # the micro model is removable; its signature test is skipped where it was removed
    from mneme_llm.decide.micro import signature
except ImportError:
    signature = None

COMPANION = """
[companion]
name = "大肥鱼"
display_language = "zh"
zone = "UTC+8"

[mood]
thresholds = {luna = 0.4}

[[roles]]
key = "teacher"
floor = 40
ceiling = 95
start = 70
names = {en = "your teacher", zh = "你的老师"}

[[roles]]
key = "creator"
floor = 80
start = 100
fades = false
unique = true

[prompts]
reflect = "Write about {user} as {name}, in {lang}: {notes}"

[messages.zh]
notes.header = "关于{who}的笔记："
"""


def write(text: str) -> str:
    path = os.path.join(tempfile.mkdtemp(), "companion.toml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def mneme(path=":memory:", **options):
    options = {"luna": False, "micro": False, "embed": False, **options}
    return Mneme(path, "t", **options)


class Recorder:
    """A chat model that answers every request and keeps what it was asked."""

    def __init__(self, reply="[]"):
        self.systems, self.messages, self.reply = [], [], reply

    def __call__(self, system, user):
        self.systems.append(system)
        self.messages.append(user)
        if system.startswith("You judge"):
            return json.dumps({"worth_remembering": {"probability": 0.9}, "mood_change": {"level": "1"},
                               "feeling": {"choice": "happy"}})
        return self.reply


class SeedTests(unittest.TestCase):
    def test_a_new_companion_takes_the_file_over_the_defaults(self):
        m = mneme(config=write(COMPANION), memory_language=None)
        self.assertEqual((m.companion_name, m.display_language), ("大肥鱼", "zh"))
        self.assertEqual(m.memory.zone.utcoffset(None), timedelta(hours=8))
        self.assertEqual(m.mood.settings.thresholds, {"luna": 0.4})
        self.assertEqual(m.mood.settings.threshold, 0.6)  # what the file leaves out is the default
        m.remember("u", "养了一只猫", kind="fact")
        self.assertTrue(m.prompt("u", "猫").startswith("关于u的笔记：\n- 养了一只猫"))
        m.relate("wu", "teacher")
        self.assertEqual(m.relations.line("wu", "吴老师"), "（吴老师是你的老师，你们很亲近。）")
        with self.assertRaises(ValueError):
            m.relate("x", "friend")  # the file's roles are the companion's roles
        origins = {row["key"]: row["origin"] for row in m.config.rows()}
        self.assertEqual(origins["companion.name"], "file")
        self.assertEqual(origins["companion.memory_language"], "default")
        self.assertEqual(sound(m.store), [])

    def test_later_the_database_keeps_its_own_copy(self):
        path = os.path.join(tempfile.mkdtemp(), "m.db")
        mneme(path, config=write(COMPANION)).close()
        m = mneme(path, config=write('[companion]\nname = "someone else"\n'))
        self.assertEqual(m.companion_name, "大肥鱼")  # the file is not read again
        m.close()
        m = mneme(path, companion_name="today only", display_language="en")
        self.assertEqual((m.companion_name, m.display_language), ("today only", "en"))  # arguments win, unstored
        self.assertEqual(m.config.get("companion.name"), "大肥鱼")
        m.display_language = "zh"  # as hosts could before: every part follows, with the companion's own sentences
        m.remember("u", "养了一只猫", kind="fact")
        self.assertTrue(m.prompt("u", "猫").startswith("关于u的笔记："))
        m.close()

    def test_a_wrong_file_stops_the_opening_and_writes_nothing(self):
        path = os.path.join(tempfile.mkdtemp(), "m.db")
        for text, said in (('[companion]\nnmae = "x"\n', "companion.nmae: no such setting"),
                           ('[mood]\nthreshold = 2\n', "mood.threshold: a number from 0 to 1"),
                           ('[voice]\nx = 1\n', "voice: no such section"),
                           ('[prompts]\nreflect = "{usr}"\n', "no placeholder {usr}"),
                           ('[mood]\nbaseline = 20\nfloor = 30\n', "floor (30) <= baseline (20)"),
                           ("[companion\n", "not valid TOML")):
            with self.assertRaises(ValueError) as caught:
                mneme(path, config=write(text))
            self.assertIn(said, str(caught.exception))
        m = mneme(path)
        self.assertEqual(m.companion_name, "the assistant")  # nothing half-written: a fresh seed now
        m.close()

    def test_no_file_seeds_the_defaults(self):
        m = mneme()
        self.assertEqual({row["key"] for row in m.config.rows()}, set(DEFAULTS))
        self.assertEqual(m.config.newer_defaults(), [])
        self.assertEqual(m.prompts, PROMPTS)


class ChangeTests(unittest.TestCase):
    def test_set_checks_each_value(self):
        m = mneme()
        m.config.set("mood.threshold", 0.5)
        m.config.set("mood.weights", {"user": 1, "speak-up": 0.5})
        self.assertEqual(m.config.get("mood.weights"), {"user": 1.0, "speak-up": 0.5})
        for key, value in (("mood.threshold", "high"), ("mood.threshold", True), ("memory.daily_quota", 2.5),
                           ("companion.zone", "Mars/Olympus"), ("companion.zone", "UTC+20"), ("mood.tell", "loud"),
                           ("companion.name", ""), ("messages.en.no.such", "x"), ("messages.english.notes.header", "x"),
                           ("prompts.nope", "x"), ("roles", [{"key": "x", "floor": 90, "ceiling": 10}]),
                           ("roles", []), ("emotions", [{"key": "happy"}, {"key": "happy"}]),
                           ("mood.skip", ["Not A Word"]), ("companion.name", "\ud800")):
            with self.assertRaises(ValueError, msg=f"{key}={value!r}"):
                m.config.set(key, value)
        self.assertEqual(m.config.get("mood.threshold"), 0.5)

    def test_apply_is_whole_or_nothing(self):
        m = mneme()
        with self.assertRaises(ValueError):
            m.config.apply({"companion": {"name": "Fei"}, "mood": {"threshold": 9}})
        self.assertEqual(m.config.get("companion.name"), "the assistant")
        self.assertEqual(m.config.apply({"companion": {"name": "Fei"}, "mood": {"threshold": 0.7}}), 2)
        self.assertEqual((m.config.get("companion.name"), m.config.get("mood.threshold")), ("Fei", 0.7))

    def test_defaults_are_loaded_only_when_asked(self):
        m = mneme()
        m.config.set("prompts.translate", "Into {language}, please.")
        # as a file seeded by an earlier version: an older default for the judge, and a key it did not have
        m.store.execute("update config set value = ? where key = 'prompts.judge'", (json.dumps("Judge it."),))
        m.store.execute("delete from config where key = 'mood.gain'")
        m.config = Config(m.store, "t")
        self.assertEqual(m.config.newer_defaults(), ["mood.gain", "prompts.judge"])  # the edited one is not listed
        self.assertEqual(m.config.get("prompts.judge"), "Judge it.")  # kept until loaded
        m.config.load_defaults(["prompts.judge"])
        self.assertEqual(m.config.get("prompts.judge"), PROMPTS["judge"])
        self.assertEqual(m.config.get("prompts.translate"), "Into {language}, please.")
        m.config.load_defaults()
        self.assertEqual(m.config.get("prompts.translate"), PROMPTS["translate"])
        self.assertEqual(m.config.newer_defaults(), [])
        with self.assertRaises(ValueError):
            m.config.load_defaults(["prompts.nope"])

    def test_a_value_spoiled_by_hand_falls_back_to_the_default_and_is_reported(self):
        m = mneme()
        m.store.execute("update config set value = '\"loud\"' where key = 'mood.tell'")
        m.store.execute("update config set value = 'not json' where key = 'mood.step'")
        m.store.execute("update config set value = '80' where key = 'mood.floor'")  # above the baseline
        m.store.execute("insert into config values ('t', 'voice.pitch', '1', 'set', 0)")
        found = Config(m.store, "t")
        self.assertEqual(set(found.invalid), {"mood.tell", "mood.step", "mood.floor", "mood.baseline",
                                              "mood.ceiling"})
        self.assertEqual(found.unknown, ["voice.pitch"])
        settings = found.mood_settings()
        self.assertEqual((settings.tell, settings.step, settings.floor), ("event", 6.0, 0.0))


class UseTests(unittest.TestCase):
    def test_the_prompts_reach_the_models(self):
        writer = Recorder()
        m = mneme(complete=writer, memory_language=None, config={"prompts": {
            "judge": "You judge. Answer in JSON.", "worth": "Did they say anything to keep?",
            "started_user": "{user} speaks to {assistant}.", "note_writer": "Notes about {user} ({today}): {known}",
            "reflect": "Impression of {user} by {name}: {notes}"}})
        m.observe("u", [("Leo", "I adopted a cat")], user_name="Leo")
        self.assertEqual(writer.systems[0], "You judge. Answer in JSON.")
        self.assertIn("Did they say anything to keep?", writer.messages[0])
        self.assertIn("Leo speaks to the assistant.", writer.messages[0])
        self.assertTrue(writer.systems[1].startswith("Notes about Leo ("))
        m.remember("u", "Has a cat", kind="fact")
        m.reflect("u", user_name="Leo", complete=Recorder("Kind."))
        self.assertEqual(m.memory.profile("u"), "Kind.")

    @unittest.skipIf(signature is None, "the micro model was removed")
    def test_a_new_question_wording_is_a_new_micro_model(self):
        before = mneme().mood.questions()[0]
        after = mneme(config={"prompts": {"mood_change": "How did the assistant's mood move?"}}).mood.questions()[0]
        self.assertNotEqual(signature(before), signature(after))
        self.assertEqual(after.instructions, "How did the assistant's mood move?")

    def test_feelings_and_a_language_of_the_companions_own(self):
        m = mneme(config={"companion": {"display_language": "ja"},
                          "emotions": [{"key": "happy"}, {"key": "proud", "names": {"ja": "誇らしい"}}],
                          "messages": {"ja": {"mood.line": "気分 {value}/100（{face}）", "cue.proud": "誇らしい。"}}})
        self.assertEqual([e.key for e in m.mood.settings.emotions], ["happy", "proud"])
        self.assertIn("proud", m.mood.questions()[1].labels)
        m.mood.apply("u", emotions={"proud": 40}, reason="")
        self.assertEqual(m.mood.describe("u"), "気分 70/100（good）; feeling: 誇らしい 40")  # the rest in English
        self.assertIn("誇らしい。", m.mood.news("u"))

    def test_export_carries_the_config_and_import_applies_it_only_when_asked(self):
        m = mneme(config={"companion": {"name": "Fei"}})
        data = m.export_data()
        self.assertIn({"key": "companion.name", "value": "Fei", "origin": "file"}, data["config"])
        other = mneme()
        other.import_data(data)
        self.assertEqual(other.config.get("companion.name"), "the assistant")
        data["config"] += [{"key": "mood.threshold", "value": 7}, {"key": "voice.pitch", "value": 1}, "junk"]
        other.import_data(data, config=True)
        self.assertEqual(other.config.get("companion.name"), "Fei")
        self.assertEqual(other.config.get("mood.threshold"), 0.6)  # the wrong rows are skipped
        self.assertEqual(sound(other.store), [])


class TomlTests(unittest.TestCase):
    def test_the_template_reads_back_as_the_defaults(self):
        self.assertEqual(load(tomllib.loads(to_toml(DEFAULTS))), DEFAULTS)

    def test_any_text_survives_the_round_trip(self):
        tricky = {"prompts.judge": 'a "q"\nb\\c """x""" \t tab \x01 end"', "companion.name": 'x\x7fy "z" \\',
                  "prompts.gloss": "\n\nlines\r\nand a trailing newline\n"}
        self.assertEqual(load(tomllib.loads(to_toml(tricky, header=""))), tricky)

    def test_message_keys_may_be_quoted_or_dotted(self):
        self.assertEqual(load(tomllib.loads('[messages.en]\n"notes.header" = "a"\nmood.line = "b"\n')),
                         {"messages.en.notes.header": "a", "messages.en.mood.line": "b"})

    def test_a_stored_config_seeds_another_file(self):
        m = mneme(config=write(COMPANION))
        copy = mneme(config=tomllib.loads(m.config.to_toml()))
        self.assertEqual(copy.config.values(), m.config.values())

    def test_check_names_the_key(self):
        with self.assertRaises(ValueError) as caught:
            check("roles", [{"key": "x", "start": 200}])
        self.assertIn("roles[0].start", str(caught.exception))


class CommandTests(unittest.TestCase):
    def run_cli(self, *args) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--db", self.path, *args])
        return code, out.getvalue(), err.getvalue().strip()

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "c.db")

    def test_the_config_commands(self):
        code, template, _ = self.run_cli("config", "template")
        self.assertEqual(load(tomllib.loads(template)), DEFAULTS)
        companion = write(COMPANION)
        self.assertIn('name = "大肥鱼"', self.run_cli("--config", companion, "config", "show", "companion")[1])
        self.assertIn("companion.name: file", self.run_cli("config", "show", "--origins")[1])
        self.run_cli("config", "set", "mood.threshold", "0.5")
        self.run_cli("config", "set", "mood.thresholds", "{luna = 0.3}")
        self.run_cli("config", "set", "companion.name", "Fei Yu")
        prompt = write("Impression of {user}:\n{notes}\n")
        self.run_cli("config", "set", "prompts.reflect", "--file", prompt)
        shown = tomllib.loads(self.run_cli("config", "show")[1])
        self.assertEqual((shown["mood"]["threshold"], shown["mood"]["thresholds"], shown["companion"]["name"],
                          shown["prompts"]["reflect"]), (0.5, {"luna": 0.3}, "Fei Yu", "Impression of {user}:\n{notes}"))
        self.assertEqual(self.run_cli("config", "set", "mood.threshold", "9")[0], 2)
        self.assertEqual(self.run_cli("config", "apply", write('[mood]\nstep = 3\n'))[1], "applied 1 keys\n")
        self.assertEqual(self.run_cli("config", "defaults", "mood.step")[1], "loaded 1 defaults\n")
        self.assertIn("every stored default", self.run_cli("config", "check")[1])
        self.assertEqual(self.run_cli("--config", write("[mood]\nstep = 99\n"), "--db", self.path + "2", "config",
                                      "check")[0], 2)

    def test_import_with_config(self):
        m = Mneme(self.path, "default", luna=False, embed=False, config={"companion": {"name": "Fei"}})
        export = os.path.join(tempfile.mkdtemp(), "e.json")
        with open(export, "w", encoding="utf-8") as handle:
            json.dump(m.export_data(), handle)
        m.close()
        self.path = os.path.join(tempfile.mkdtemp(), "d.db")
        self.run_cli("import", export)
        self.assertIn('name = "the assistant"', self.run_cli("config", "show", "companion")[1])
        self.run_cli("import", export, "--with-config")
        self.assertIn('name = "Fei"', self.run_cli("config", "show", "companion")[1])


class StoredTests(unittest.TestCase):
    def test_stored_reads_as_its_name(self):
        self.assertEqual(repr(STORED), "STORED")
        self.assertIs(configs.STORED, STORED)


if __name__ == "__main__":
    unittest.main()
