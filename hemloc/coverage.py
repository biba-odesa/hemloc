"""Compatibility alias for hemlock.coverage."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.coverage")
