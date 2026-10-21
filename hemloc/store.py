"""Compatibility alias for hemlock.store."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.store")
