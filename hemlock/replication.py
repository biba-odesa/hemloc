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
from .installed import application_identity
from .protocol import (REPLICATION_PROTOCOL_VERSION, NODE_HEADER, VERSION_HEADER, EXCHANGE_HEADER,
                       APP_HEADER, ProtocolFailure, app_version, parse_version, failure)


class PeerUnavailable(RuntimeError):
    pass


class PeerAuthenticationFailed(PeerUnavailable):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PeerUnavailable("Replication redirects are forbidden")


class PeerTransport:
    def __init__(self, config, *, protocol_version=REPLICATION_PROTOCOL_VERSION):
        self.config = config
        self.protocol_version=protocol_version
        self.application_version=application_identity()['version']
        self.exchange_token=None
        self.exchange_until=0
        self.peer_identity=None
        self.token = Path(config.token_file).read_text().strip() if config.token_file else ""
        if config.peer_url and (len(self.token) < 32 or any(c.isspace() for c in self.token)):
            raise Invalid("Replication token must contain at least 32 non-whitespace characters")
        context = ssl.create_default_context(cafile=config.ca or None)
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())

    def authorized(self, authorization, peer_id):
        return bool(self.token and peer_id == self.config.peer_node_id and
                    secrets.compare_digest((authorization or "").encode(), ("Bearer " + self.token).encode()))

    def _check_response(self,headers):
        version=parse_version(headers.get(VERSION_HEADER))
        peer_app=(self.peer_identity or {}).get('application_version')
        if version!=self.protocol_version:
            raise ProtocolFailure('peer_upgrade_required' if version is None else 'protocol_mismatch',self.protocol_version,version,self.application_version,peer_app)
        if not secrets.compare_digest(headers.get(EXCHANGE_HEADER,''),self.exchange_token or ''):
            raise ProtocolFailure('handshake_required',self.protocol_version,self.protocol_version,self.application_version,peer_app)

    def _request(self,path,query=None,*,handshake=False):
        if not self.config.peer_url:raise PeerUnavailable('Peer is not configured')
        url=self.config.peer_url.rstrip('/')+path
        if query:url+='?'+urlencode(query)
        headers={'Authorization':'Bearer '+self.token,NODE_HEADER:self.config.node_id,
                 VERSION_HEADER:str(self.protocol_version)}
        if app_version(self.application_version):headers[APP_HEADER]=self.application_version
        if not handshake:headers[EXCHANGE_HEADER]=self.exchange_token
        limit=16384 if handshake else 128*1024*1024
        request=Request(url,headers=headers)
        try:
            with self.opener.open(request,timeout=self.config.timeout) as response:
                if response.geturl()!=url:raise PeerUnavailable('Replication redirects are forbidden')
                if not handshake:self._check_response(response.headers)
                declared=response.headers.get('Content-Length')
                if declared is not None and not 0<=int(declared)<=limit:raise PeerUnavailable('Invalid peer response size')
                raw=response.read(limit+1)
                if len(raw)>limit or (declared is not None and len(raw)!=int(declared)):
                    raise PeerUnavailable('Incomplete or oversized peer response')
                try:return json.loads(raw)
                except ValueError:
                    if handshake:raise ProtocolFailure('peer_upgrade_required',self.protocol_version,local_app=self.application_version) from None
                    raise
        except HTTPError as exc:
            try:
                if exc.code in (401,403):raise PeerAuthenticationFailed('Peer authentication failed') from None
                if exc.code in (426,412,428):
                    try:details=json.loads(exc.read(16385))
                    except (ValueError,OSError):details={}
                    if not isinstance(details,dict):details={}
                    code={426:'peer_upgrade_required',412:'protocol_mismatch',428:'handshake_required'}[exc.code]
                    raise ProtocolFailure(code,self.protocol_version,details.get('local_protocol_version'),self.application_version,details.get('local_application_version')) from None
                if handshake and exc.code in (404,405,501):
                    raise ProtocolFailure('peer_upgrade_required',self.protocol_version,local_app=self.application_version) from None
                if exc.code==409:
                    if not handshake:self._check_response(exc.headers)
                    raise NeedSnapshot('Peer requires snapshot') from None
                raise PeerUnavailable('Peer rejected request') from None
            finally:exc.close()
        except (OSError,ValueError,HTTPException):raise PeerUnavailable('Peer transport failed') from None

    def handshake(self):
        self.exchange_token=None;self.exchange_until=0;self.peer_identity=None
        peer=self._request('/replication/handshake',handshake=True)
        if not isinstance(peer,dict):raise ProtocolFailure('peer_upgrade_required',self.protocol_version,local_app=self.application_version)
        if peer.get('node_id') not in (None,self.config.peer_node_id):raise PeerAuthenticationFailed('Unexpected peer identity')
        raw_version=peer.get('replication_protocol_version')
        version=parse_version(raw_version) if type(raw_version) is int else None
        if version!=self.protocol_version:
            raise ProtocolFailure('peer_upgrade_required' if version is None else 'protocol_mismatch',self.protocol_version,version,self.application_version,peer.get('application_version'))
        if peer.get('node_id')!=self.config.peer_node_id:raise PeerAuthenticationFailed('Unexpected peer identity')
        token=peer.get('exchange_token');lease=peer.get('lease_seconds')
        if (peer.get('compatible') is not True or peer.get('role') not in ('master','slave')
                or not isinstance(token,str) or not 32<=len(token)<=256
                or type(lease) is not int or not 0<lease<=30):
            raise ProtocolFailure('handshake_required',self.protocol_version,version,self.application_version,peer.get('application_version'))
        self.exchange_token=token;self.exchange_until=time.monotonic()+lease;self.peer_identity=peer
        return peer

    def get(self,path,query=None):
        if path=='/replication/handshake':return self.handshake()
        if not self.exchange_token or time.monotonic()>=self.exchange_until:self.handshake()
        try:return self._request(path,query)
        except ProtocolFailure:
            self.exchange_token=None;self.exchange_until=0
            raise


def observe_peer(store, transport, *, persist_ack=True):
    """Read live authenticated identity; persist an acknowledgement only when changed."""
    config = store.config
    negotiated=transport.handshake()
    peer = transport.get('/replication/status')
    if peer.get('replication_protocol_version')!=negotiated.get('replication_protocol_version'):
        raise ProtocolFailure('handshake_required',getattr(transport,'protocol_version',REPLICATION_PROTOCOL_VERSION))
    if peer.get('node_id') != config.peer_node_id:
        raise Conflict('Unexpected peer identity')
    if peer.get('role') not in ('master', 'slave'):
        raise Conflict('Invalid peer role')
    now = time.time()
    store.set_local('peer', {'at': now, 'status': peer})
    store.set_local('peer_compatibility',{'ok':True,'at':now,'local_protocol_version':getattr(transport,'protocol_version',REPLICATION_PROTOCOL_VERSION),
                                        'peer_protocol_version':negotiated['replication_protocol_version'],
                                        'local_application_version':getattr(transport,'application_version',None),
                                        'peer_application_version':negotiated.get('application_version')})
    if persist_ack:commit_peer_ack(store,peer)
    return peer


def commit_peer_ack(store,peer):
    if store.config.role=='master' and peer['role']=='slave':
        ack=store.local('peer_ack',{})
        if (ack.get('history'),ack.get('sequence'))!=(peer.get('history'),peer.get('sequence')):
            store.set_local('peer_ack',{'at':time.time(),'history':peer.get('history'),'sequence':peer.get('sequence')})


class Replicator:
    def __init__(self, store, transport):
        self.store, self.transport = store, transport

    def step(self):
        """One bounded polling cycle; failures never erase replicated data."""
        config = self.store.config
        try:
            peer = observe_peer(self.store, self.transport,persist_ack=False)
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
                local = self.store.info()
                snapshot=None;events=None
                if local['history']!=peer.get('history'):
                    snapshot=self.transport.get('/replication/snapshot')
                    local=snapshot['payload']
                try:
                    events=self.transport.get('/replication/events',{'history':local['history'],'cursor':local['sequence']})
                except NeedSnapshot:
                    snapshot=self.transport.get('/replication/snapshot')
                # Fetch and validate every response before any remote state/ack commit.
                if snapshot is not None:self.store.install_snapshot(snapshot)
                if events is not None:self.store.apply_events(events)
                if peer.get('security_ack'):self.store.set_local('security_ack',peer['security_ack'])
            commit_peer_ack(self.store,peer)
            self.store.set_local("sync", {"ok": True, "at": time.time(), "last_success": time.time(), "error": ""})
        except ProtocolFailure as exc:
            failure(self.store,exc)
            raise
        except (Conflict, Invalid, PeerUnavailable, OSError, ValueError) as exc:
            code = 'two_masters' if isinstance(exc, SplitBrain) else ('peer_auth_failed' if isinstance(exc,PeerAuthenticationFailed) else 'peer_sync_failed')
            message = ('Two masters detected; isolate the former master; no state is merged'
                       if isinstance(exc, SplitBrain) else 'Peer synchronization failed; working data retained')
            self.store.set_local('peer_compatibility',{'ok':False,'at':time.time(),'code':code})
            previous = self.store.local("sync", {})
            last_success = previous.get("last_success") or (previous.get("at") if previous.get("ok") else None)
            self.store.set_local("sync", {"ok": False, "at": time.time(), "code": code, "error": message, "last_success": last_success})
            raise
