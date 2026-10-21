"""Compatibility alias for hemlock.history."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.history")
