import re
import unittest

from mneme_llm.i18n import LANGUAGES, MESSAGES, say


class I18nTests(unittest.TestCase):
    def test_every_language_has_every_sentence_and_placeholder(self):
        english = MESSAGES["en"]
        for lang in LANGUAGES:
            self.assertEqual(set(MESSAGES[lang]), set(english), lang)
            for key, text in MESSAGES[lang].items():
                self.assertEqual(set(re.findall(r"{(\w+)}", text)), set(re.findall(r"{(\w+)}", english[key])),
                                 f"{lang}:{key}")

    def test_unknown_languages_fall_back_to_english(self):
        self.assertEqual(say("fr", "tool.kept", id=3), "Kept as #3.")


if __name__ == "__main__":
    unittest.main()
