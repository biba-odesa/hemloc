"""Compatibility alias for hemlock.workers."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.workers")
