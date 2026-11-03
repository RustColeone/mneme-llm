"""Whether this install has the removable tier, so its tests are skipped where it was deleted."""

import importlib.util
import unittest

UNIFY = importlib.util.find_spec("mneme_llm.meaning.unify") is not None

needs_unify = unittest.skipUnless(UNIFY, "the unify tier is not installed")
