"""Compatibility alias for hemlock.notifications."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.notifications")
