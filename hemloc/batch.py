"""Compatibility alias for hemlock.batch."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.batch")
