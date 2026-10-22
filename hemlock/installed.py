"""Public runtime identity from installed distribution metadata, never Git."""
from importlib import metadata
import json
import re


def application_identity():
    try:
        distribution = metadata.distribution('hemlock')
    except metadata.PackageNotFoundError:
        return {'version':None, 'build_commit':None}
    commit = None
    try:
        # pip records a commit for installations from a VCS URL (PEP 610).
        direct = json.loads(distribution.read_text('direct_url.json') or '{}')
        candidate = direct.get('vcs_info', {}).get('commit_id', '')
        if isinstance(candidate, str) and re.fullmatch(r'[0-9a-fA-F]{7,64}', candidate):
            commit = candidate
    except (ValueError, AttributeError, OSError, TypeError):
        pass
    return {'version':distribution.version, 'build_commit':commit}
