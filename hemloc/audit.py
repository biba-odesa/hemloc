"""Compatibility alias for hemlock.audit."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.audit")
