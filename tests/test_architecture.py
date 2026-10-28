"""The browsable architecture page (docs/architecture) is made from the code by tools/architecture.py, so it must match
the code: every Python file, class and function, with its source. (Skipped where it cannot be made: outside a git
checkout, as in an unpacked sdist, or with files deleted from the checkout, as CI's run without the removable tiers.)"""

import ast
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "architecture.py"
DATA = ROOT / "docs" / "architecture" / "data.js"


def checkout_is_whole() -> bool:
    """A git checkout with the tool, the page and every tracked file in place."""
    if not (TOOL.is_file() and DATA.is_file() and shutil.which("git")):
        return False
    listed = subprocess.run(["git", "ls-files", "--", "mneme_llm", "tests", "tools"], cwd=ROOT, capture_output=True,
                            text=True)
    return listed.returncode == 0 and bool(listed.stdout) and all((ROOT / path).is_file() for path in listed.stdout.split())


@unittest.skipUnless(checkout_is_whole(), "not a whole git checkout: the page is made from one")
class ArchitecturePageTests(unittest.TestCase):
    def test_the_page_matches_the_code(self):
        result = subprocess.run([sys.executable, str(TOOL), "--check"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         result.stderr + "\nRun `python tools/architecture.py` and commit docs/architecture/data.js.")

    def test_every_function_is_there_with_its_own_source(self):
        data = json.loads(DATA.read_text(encoding="utf-8").split("window.ARCH = ", 1)[1].rstrip().rstrip(";"))
        path = "mneme_llm/people.py"
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        defined = {f"{node.name}.{item.name}" for node in tree.body if isinstance(node, ast.ClassDef)
                   for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
        listed = {item["id"]: item for item in data["files"][path]["symbols"]}
        self.assertLessEqual(defined, set(listed))
        writing = listed["Resolves.writing"]
        lines = data["files"][path]["text"].splitlines()[writing["line"] - 1:writing["end"]]
        self.assertTrue(lines[0].strip().startswith("@contextlib.contextmanager"))  # the pane shows exactly this method

    def test_the_top_map_and_the_guide_point_at_real_code(self):
        data = json.loads(DATA.read_text(encoding="utf-8").split("window.ARCH = ", 1)[1].rstrip().rstrip(";"))
        site = (ROOT / "docs" / "architecture" / "site.js").read_text(encoding="utf-8")
        import re
        text = r'"(?:[^"\\]|\\.)*"'  # a JavaScript string, escaped quotes and all
        steps = re.findall(rf'step\({text}, {text}, "([^"]+)", "([^"]+)"', site)
        self.assertEqual(len(steps), site.count('step("'), "every guide step is checked")
        for path, symbol in steps:
            ids = {item["id"] for item in data["files"][f"mneme_llm/{path}"]["symbols"]}
            self.assertIn(symbol, ids, f"the guide names {path}::{symbol}")
        for name in re.findall(r'file\("([^"]+\.py)"', site):
            self.assertIn(f"mneme_llm/{name}", data["files"], f"the top map names {name}")


if __name__ == "__main__":
    unittest.main()
