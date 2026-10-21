"""Compatibility alias for hemlock.domain."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.domain")
