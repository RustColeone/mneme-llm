"""The tests' temporary files go in one folder of their own, removed when the run ends, so a test that makes a folder
with `tempfile.mkdtemp()` and leaves it there leaves nothing behind."""

import atexit
import shutil
import tempfile

tempfile.tempdir = tempfile.mkdtemp(prefix="mneme-llm-tests-")
atexit.register(shutil.rmtree, tempfile.tempdir, ignore_errors=True)
