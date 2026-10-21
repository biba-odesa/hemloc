"""Compatibility alias for hemlock.gobgp."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.gobgp")
