#!/usr/bin/env python3
"""Credential-free manual notification test sink; install outside the application tree."""
import json
import sys

raw = sys.stdin.buffer.read(65537)
if len(raw) > 65536:
    raise SystemExit(2)
message = json.loads(raw.decode('utf-8'))
if set(message) != {'subject', 'body'} or any(not isinstance(v, str) for v in message.values()):
    raise SystemExit(2)
# Replace this sink with an administrator-managed channel implementation.
print(message['subject'])
print(message['body'])
