"""Compatibility alias for hemlock.auth."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.auth")
