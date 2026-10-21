"""Compatibility alias for hemlock.irr."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.irr")
