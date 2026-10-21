"""Compatibility alias for hemlock.maintenance."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.maintenance")
