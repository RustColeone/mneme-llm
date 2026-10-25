"""Which removable tiers this install has, so tests of a tier are skipped where it was deleted."""

import importlib.util
import unittest

DECIDE_MICRO = importlib.util.find_spec("mneme_llm.decide.micro") is not None
CENTROIDS = importlib.util.find_spec("mneme_llm.meaning.micro") is not None
UNIFY = importlib.util.find_spec("mneme_llm.meaning.unify") is not None

needs_decide_micro = unittest.skipUnless(DECIDE_MICRO, "the decision micro model is not installed")
needs_centroids = unittest.skipUnless(CENTROIDS, "the meaning micro tier (word centroids) is not installed")
needs_unify = unittest.skipUnless(UNIFY, "the unify tier is not installed")
