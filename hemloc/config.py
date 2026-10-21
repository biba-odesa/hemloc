"""Compatibility alias for hemlock.config."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.config")
