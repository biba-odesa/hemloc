"""Compatibility alias for hemlock.cli."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.cli")
