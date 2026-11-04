"""The tuner page (docs/tune) keeps its own copy of her bars, ends and side names, since a static page cannot import
Python: they must stay those of mneme_llm.gut."""

import ast
import re
import unittest
from pathlib import Path

import mneme_llm.gut as G

TUNE = Path(__file__).resolve().parents[1] / "docs" / "tune" / "tune.js"


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


if __name__ == "__main__":
    unittest.main()
