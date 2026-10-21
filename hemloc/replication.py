"""Compatibility alias for hemlock.replication."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("hemlock.replication")
