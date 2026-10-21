"""Compatibility alias for hemlock.web."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.web")
