"""Compatibility alias for hemlock.retention."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.retention")
