"""Authenticated, direct HTTPS peer transport and polling protocol."""

from pathlib import Path
from http.client import HTTPException
import secrets
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, HTTPSHandler, HTTPRedirectHandler, Request, build_opener
import json

from .domain import Conflict, Invalid, NeedSnapshot, SplitBrain


class PeerUnavailable(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PeerUnavailable("Replication redirects are forbidden")


class PeerTransport:
    def __init__(self, config):
        self.config = config
        self.token = Path(config.token_file).read_text().strip() if config.token_file else ""
        if config.peer_url and (len(self.token) < 32 or any(c.isspace() for c in self.token)):
            raise Invalid("Replication token must contain at least 32 non-whitespace characters")
        context = ssl.create_default_context(cafile=config.ca or None)
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())

    def authorized(self, authorization, peer_id):
        return bool(self.token and peer_id == self.config.peer_node_id and
                    secrets.compare_digest((authorization or "").encode(), ("Bearer " + self.token).encode()))

    def get(self, path, query=None):
        if not self.config.peer_url:
            raise PeerUnavailable("Peer is not configured")
        url = self.config.peer_url.rstrip("/") + path
        if query:
            url += "?" + urlencode(query)
        request = Request(url, headers={"Authorization": "Bearer " + self.token,
                                       "X-Hemlock-Node": self.config.node_id})
        try:
            with self.opener.open(request, timeout=self.config.timeout) as response:
                if response.geturl() != url:
                    raise PeerUnavailable("Replication redirects are forbidden")
                declared = response.headers.get('Content-Length')
                if declared is not None and not 0 <= int(declared) <= 128 * 1024 * 1024:
                    raise PeerUnavailable('Invalid peer response size')
                raw = response.read(128 * 1024 * 1024 + 1)
                if declared is not None and len(raw) != int(declared):
                    raise PeerUnavailable('Incomplete peer response')
                if len(raw) > 128 * 1024 * 1024:
                    raise PeerUnavailable("Peer response exceeds size limit")
                return json.loads(raw)
        except HTTPError as exc:
            if exc.code == 409:
                raise NeedSnapshot("Peer requires snapshot") from None
            raise PeerUnavailable("Peer rejected request") from None
        except (OSError, ValueError, HTTPException) as exc:
            raise PeerUnavailable("Peer transport failed") from None


def observe_peer(store, transport):
    """Read live authenticated identity; persist an acknowledgement only when changed."""
    config = store.config
    peer = transport.get('/replication/status')
    if peer.get('node_id') != config.peer_node_id:
        raise Conflict('Unexpected peer identity')
    if peer.get('role') not in ('master', 'slave'):
        raise Conflict('Invalid peer role')
    now = time.time()
    store.set_local('peer', {'at': now, 'status': peer})
    if config.role == 'master' and peer['role'] == 'slave':
        ack = store.local('peer_ack', {})
        if (ack.get('history'), ack.get('sequence')) != (peer.get('history'), peer.get('sequence')):
            store.set_local('peer_ack', {'at': now, 'history': peer.get('history'), 'sequence': peer.get('sequence')})
    return peer


class Replicator:
    def __init__(self, store, transport):
        self.store, self.transport = store, transport

    def step(self):
        """One bounded polling cycle; failures never erase replicated data."""
        config = self.store.config
        try:
            peer = observe_peer(self.store, self.transport)
            if config.role == "master":
                if peer["role"] == "master":
                    raise SplitBrain("Two masters detected; isolate the former master")
                with self.store.connect() as db:
                    audit_history = self.store.meta(db, 'peer_security_history')
                    audit_cursor = int(self.store.meta(db, 'peer_security_cursor', '0'))
                self.store.ingest_security(self.transport.get('/replication/local-audit',
                                          {'history': audit_history, 'after': audit_cursor}))
            else:
                if peer["role"] != "master":
                    raise Conflict("No master at configured peer")
                if peer.get("security_ack"):
                    self.store.set_local("security_ack", peer["security_ack"])
                local = self.store.info()
                if local["history"] != peer.get("history"):
                    self.store.install_snapshot(self.transport.get("/replication/snapshot", {"protocol":2}))
                    local = self.store.info()
                try:
                    events = self.transport.get("/replication/events", {"history": local["history"], "cursor": local["sequence"], "protocol":2})
                    self.store.apply_events(events)
                except NeedSnapshot:
                    self.store.install_snapshot(self.transport.get("/replication/snapshot", {"protocol":2}))
            self.store.set_local("sync", {"ok": True, "at": time.time(), "last_success": time.time(), "error": ""})
        except (Conflict, Invalid, PeerUnavailable, OSError, ValueError) as exc:
            code = 'two_masters' if isinstance(exc, SplitBrain) else 'peer_sync_failed'
            message = ('Two masters detected; isolate the former master; no state is merged'
                       if isinstance(exc, SplitBrain) else 'Peer synchronization failed; working data retained')
            previous = self.store.local("sync", {})
            last_success = previous.get("last_success") or (previous.get("at") if previous.get("ok") else None)
            self.store.set_local("sync", {"ok": False, "at": time.time(), "code": code, "error": message, "last_success": last_success})
            raise
