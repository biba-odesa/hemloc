#!/usr/bin/env python3
"""Deterministic IRR fixture. This script never accesses the network."""
import sys

if sys.argv[-1] != 'AS64500':
    raise SystemExit(1)
print('2001:db8::/32' if '-6' in sys.argv else '192.0.2.0/24')
