"""Compatibility alias for hemlock.service."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.service")
