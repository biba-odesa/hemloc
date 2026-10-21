"""Compatibility alias for hemlock.presentation."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.presentation")
