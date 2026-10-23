"""One replication wire protocol; independent of application release numbering."""
from collections import OrderedDict
import hashlib
import re
import secrets
from threading import Lock
import time

REPLICATION_PROTOCOL_VERSION = 3
NODE_HEADER = 'X-Hemlock-Node'
VERSION_HEADER = 'X-Hemlock-Protocol'
EXCHANGE_HEADER = 'X-Hemlock-Exchange'
APP_HEADER = 'X-Hemlock-App-Version'
LEASE_SECONDS = 30


def app_version(value):
    return value if isinstance(value,str) and re.fullmatch(r'[0-9][A-Za-z0-9.!+_-]{0,63}',value) else None


def parse_version(value):
    if type(value) is int:return value if 0 < value <= 2147483647 else None
    if isinstance(value,str) and re.fullmatch('[1-9][0-9]{0,9}',value):
        number=int(value)
        return number if number<=2147483647 else None
    return None


class ProtocolFailure(RuntimeError):
    def __init__(self,code,local,peer=None,local_app=None,peer_app=None):
        self.code=code
        self.details={'local_protocol_version':local,'peer_protocol_version':parse_version(peer),
                      'local_application_version':app_version(local_app),'peer_application_version':app_version(peer_app)}
        super().__init__({'protocol_mismatch':'Protocol version mismatch','peer_upgrade_required':'Peer upgrade required',
                          'handshake_required':'Replication handshake required'}[code])


def failure(store,error):
    previous=store.local('sync',{})
    store.set_local('peer_compatibility',{'ok':False,'at':time.time(),'code':error.code,**error.details})
    store.set_local('sync',{'ok':False,'at':time.time(),'code':error.code,'error':str(error),
                           'last_success':previous.get('last_success') or (previous.get('at') if previous.get('ok') else None)})


def confirmed(store,now=None):
    state=store.local('peer_compatibility',{})
    now=time.time() if now is None else now
    local=getattr(store,'replication_protocol_version',REPLICATION_PROTOCOL_VERSION)
    if getattr(store.config,'tls_mode','legacy_ca')=='pinned':
        from .tls import Trust,own_info
        try:pin=Trust(store.config).pin();own=own_info(store.config)
        except (ValueError,OSError):return False
        if (not pin or pin['not_after']<=now or own['not_after']<=now or state.get('peer_spki')!=pin['fingerprint']
                or state.get('own_spki')!=own['fingerprint']):return False
    return (state.get('ok') is True and state.get('local_protocol_version')==local
            and state.get('peer_protocol_version')==local and 0<=now-state.get('at',0)<=LEASE_SECONDS)


class Gate:
    """Bounded, process-local proof of a successful authenticated handshake."""
    def __init__(self,store,version=REPLICATION_PROTOCOL_VERSION,application_version=None):
        self.store=store;self.version=version;self.application_version=app_version(application_version)
        self.tokens=OrderedDict();self.lock=Lock()

    def identity(self):
        return {'node_id':self.store.config.node_id,'role':self.store.config.role,
                'replication_protocol_version':self.version,'application_version':self.application_version}

    def check_version(self,headers):
        peer=parse_version(headers.get(VERSION_HEADER))
        if peer!=self.version:
            error=ProtocolFailure('peer_upgrade_required' if peer is None else 'protocol_mismatch',
                                  self.version,peer,self.application_version,headers.get(APP_HEADER))
            with self.lock:self.tokens.clear()
            failure(self.store,error)
            raise error

    def handshake(self,headers):
        identity=self.identity()
        try:self.check_version(headers)
        except ProtocolFailure as error:return identity|{'compatible':False,'code':error.code}
        token=secrets.token_urlsafe(32);now=time.monotonic()
        with self.lock:
            self.tokens=OrderedDict((key,value) for key,value in self.tokens.items() if value[2]>now)
            while len(self.tokens)>=64:self.tokens.popitem(last=False)
            self.tokens[hashlib.sha256(token.encode()).digest()]=(headers.get(NODE_HEADER),self.version,now+LEASE_SECONDS)
        return identity|{'compatible':True,'exchange_token':token,'lease_seconds':LEASE_SECONDS}

    def require(self,headers):
        self.check_version(headers)
        token=headers.get(EXCHANGE_HEADER,'')
        key=hashlib.sha256(token.encode()).digest() if isinstance(token,str) and len(token)<=256 else b''
        with self.lock:record=self.tokens.get(key)
        if not record or record[:2]!=(headers.get(NODE_HEADER),self.version) or record[2]<=time.monotonic():
            error=ProtocolFailure('handshake_required',self.version,self.version,self.application_version,headers.get(APP_HEADER))
            failure(self.store,error)
            raise error
        return {VERSION_HEADER:str(self.version),EXCHANGE_HEADER:token}
