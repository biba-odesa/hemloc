"""Local certificate lifecycle, explicit SPKI approval and pinned mTLS transport."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import base64
import fcntl
import hashlib
import http.client
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .domain import Conflict, Invalid

LOG = logging.getLogger('uvicorn.error.tls')
LIMIT = 32768
UTC = timezone.utc


class TLSFailure(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def fingerprint(cert):
    raw = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')


def public_info(cert):
    return {'fingerprint':fingerprint(cert), 'algorithm':'SHA256 SPKI',
            'valid_from':cert.not_valid_before_utc.isoformat(),'valid_until':cert.not_valid_after_utc.isoformat(),
            'not_before':cert.not_valid_before_utc.timestamp(), 'not_after':cert.not_valid_after_utc.timestamp()}


def parse_certificate(data):
    try:
        return x509.load_pem_x509_certificate(data) if data.startswith(b'-----') else x509.load_der_x509_certificate(data)
    except (ValueError, TypeError):
        raise Invalid('TLS certificate is damaged or not a supported X.509 certificate') from None


def valid_now(cert):
    now = datetime.now(UTC)
    if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
        raise TLSFailure('tls_certificate_invalid', 'Peer certificate is expired or not yet valid')


def private(path, directory=False, *, purpose="TLS"):
    try:info = path.lstat()
    except FileNotFoundError:raise Invalid(purpose+' file or directory is missing: '+path.name) from None
    correct = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    expected=0o700 if directory else 0o600
    if not correct or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode)!=expected:
        raise Invalid(purpose+' path must be service-owned, nonsymlink and mode '+('0700: ' if directory else '0600: ')+path.name)


def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def write_private(path, value):
    temporary=path.with_name('.'+path.name+'-'+str(uuid.uuid4()))
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(value);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path);fsync_dir(path.parent)
    finally:temporary.unlink(missing_ok=True)


class Trust:
    """One local, bounded, atomically updated trust/audit file; never SQLite."""
    def __init__(self,config):
        self.config=config;self.root=Path(config.tls_state_dir)
        self.root.mkdir(mode=0o700,exist_ok=True)
        private(self.root,True)
        self.path=self.root/'trust.json';self.lock_path=self.root/'trust.lock'

    @contextmanager
    def locked(self):
        fd=os.open(self.lock_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            private(self.lock_path);fcntl.flock(fd,fcntl.LOCK_EX)
            yield
        finally:os.close(fd)

    def read(self):
        if not self.path.exists() and not self.path.is_symlink():return {'version':1,'pin':None,'candidate':None,'events':[],'warned':[]}
        private(self.path)
        try:
            if self.path.stat().st_size>2*1024*1024:raise ValueError()
            data=json.loads(self.path.read_text())
            if data.get('version')!=1 or not isinstance(data.get('events'),list) or not isinstance(data.get('warned'),list):raise ValueError()
            pin=data.get('pin')
            if pin:
                cert=parse_certificate(base64.b64decode(pin['certificate'],validate=True))
                if pin['fingerprint']!=fingerprint(cert) or not isinstance(pin['node_id'],str):raise ValueError()
            return data
        except (ValueError,KeyError,TypeError,AttributeError):raise Invalid('Local TLS trust file is damaged; it was not replaced') from None

    def save(self,data):
        encoded=json.dumps(data,ensure_ascii=True).encode()
        if len(encoded)>2*1024*1024:raise Invalid('Local TLS audit requires archival before further changes')
        write_private(self.path,encoded)

    def event(self,data,action,actor='system',**fields):
        data['events'].append({'id':str(uuid.uuid4()),'at':time.time(),'node':self.config.node_id,'actor':actor,'action':action,'result':'success',**fields})

    def pin(self):
        pin=self.read().get('pin')
        return pin if pin and pin['node_id']==self.config.peer_node_id else None

    def status(self):
        data=self.read();pin=data.get('pin');candidate=data.get('candidate')
        public=('node_id','fingerprint','algorithm','not_before','not_after','valid_from','valid_until','approved_peer')
        return {'mode':self.config.tls_mode,'expected_node_id':self.config.peer_node_id,'peer_url':self.config.peer_url,
                'pin':{k:v for k,v in pin.items() if k in public} if pin else None,
                'candidate':{k:v for k,v in candidate.items() if k in public} if candidate else None,
                'events':data['events'][-20:]}

    def discover(self):
        if not self.config.peer_url:raise Invalid('Peer URL is not configured')
        candidate=discover(self.config)
        with self.locked():
            data=self.read()
            changed=data.get('candidate')!=candidate
            if changed:
                data['candidate']=candidate
                pin=data.get('pin')
                if pin and pin['node_id']==self.config.peer_node_id==candidate['node_id'] and pin['fingerprint']==candidate['fingerprint']:
                    data['pin']=candidate
                self.save(data)
        return {k:v for k,v in candidate.items() if k!='certificate'}

    def approve(self,expected,actor='root:cli'):
        if not isinstance(expected,str) or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}',expected):
            with self.locked():
                data=self.read();self.event(data,'peer.approval.invalid',actor,result='invalid');self.save(data)
            raise Invalid('Use the complete SHA256 SPKI fingerprint')
        # Refresh outside the lock; check both the viewed candidate and actual connection key.
        try:current=discover(self.config)
        except TLSFailure as exc:
            with self.locked():
                data=self.read();self.event(data,'peer.approval.failed',actor,result='failed',reason=exc.code);self.save(data)
            raise
        with self.locked():
            data=self.read();viewed=data.get('candidate')
            if not viewed or viewed['fingerprint']!=expected or current['fingerprint']!=expected or viewed.get('node_id')!=current.get('node_id'):
                data['candidate']=current;self.event(data,'peer.approval.conflict',actor,result='conflict');self.save(data)
                raise Conflict('Peer candidate changed; inspect and confirm the new fingerprint')
            if current['node_id']!=self.config.peer_node_id:
                self.event(data,'peer.approval.denied',actor,result='denied');self.save(data)
                raise Conflict('Claimed peer node ID does not match the expected node ID')
            if Path(self.config.cert).exists() and current['fingerprint']==own_info(self.config)['fingerprint']:
                self.event(data,'peer.approval.denied',actor,result='denied');self.save(data)
                raise Conflict('Each node requires its own TLS key; the peer uses this node key')
            existing=data.get('pin')
            if existing and (existing['fingerprint']!=expected or existing['node_id']!=self.config.peer_node_id):
                self.event(data,'peer.approval.denied',actor,result='denied');self.save(data)
                raise Conflict('Revoke existing trust explicitly before approving a replacement key or identity')
            data['pin']=current;self.event(data,'peer.approved',actor,fingerprint=expected,node_id=current['node_id']);self.save(data)
        LOG.info('TLS peer approval saved for configured identity')
        return self.status()

    def revoke(self,expected,actor='root:cli'):
        with self.locked():
            data=self.read();pin=data.get('pin')
            if not pin or pin['fingerprint']!=expected:
                self.event(data,'peer.revocation.conflict',actor,result='conflict');self.save(data)
                raise Conflict('Trusted fingerprint changed or no trust exists')
            data['pin']=None;self.event(data,'peer.revoked',actor,fingerprint=expected,node_id=pin['node_id']);self.save(data)
        LOG.warning('TLS peer approval revoked')
        return self.status()


def own_info(config):
    cert=parse_certificate(Path(config.cert).read_bytes())
    return {'node_id':config.node_id,**public_info(cert)}


def ensure_identity(config, *, rotate_expired=True):
    """Atomic directory publication prevents a partially installed certificate pair."""
    if config.tls_mode!='pinned':return None
    trust=Trust(config)
    cert_path,key_path=Path(config.cert),Path(config.key);parent=cert_path.parent
    with trust.locked():
        exists=[p.exists() or p.is_symlink() for p in (cert_path,key_path)]
        if exists[0]!=exists[1]:raise Invalid('Only one TLS certificate/key file exists; restore or remove the pair explicitly')
        expired=False
        if any(exists):
            private(parent,True);private(cert_path);private(key_path)
            cert=parse_certificate(cert_path.read_bytes())
            try:key=serialization.load_pem_private_key(key_path.read_bytes(),password=None)
            except (ValueError,TypeError):raise Invalid('TLS private key is damaged, encrypted or unsupported') from None
            if key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)!=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo):
                raise Invalid('TLS certificate does not match the private key')
            if cert.not_valid_before_utc>datetime.now(UTC):raise Invalid('Local TLS certificate is not yet valid')
            expired=cert.not_valid_after_utc<=datetime.now(UTC)
            if not expired or not rotate_expired:return public_info(cert)
        if parent.exists():
            private(parent,True)
            if set(parent.iterdir())-({cert_path,key_path} if expired else set()):raise Invalid('TLS identity directory contains unrelated files; it was not replaced')
        if not parent.parent.exists():raise Invalid('TLS identity parent directory must be prepared by the installer')
        key=ec.generate_private_key(ec.SECP256R1());now=datetime.now(UTC)
        names=[]
        for value in config.tls_names or (config.host,):
            try:
                address=ipaddress.ip_address(value)
                if address.is_unspecified:raise Invalid('Configure tls names with the management IP/DNS, not a wildcard listener')
                names.append(x509.IPAddress(address))
            except ValueError:names.append(x509.DNSName(value))
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,config.node_id)])
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=config.tls_days))
              .add_extension(x509.SubjectAlternativeName(names),False).add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
              .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH,ExtendedKeyUsageOID.CLIENT_AUTH]),False)
              .sign(key,hashes.SHA256()))
        staging=parent.with_name('.'+parent.name+'-new-'+str(uuid.uuid4()));staging.mkdir(mode=0o700)
        try:
            write_private(staging/key_path.name,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            write_private(staging/cert_path.name,cert.public_bytes(serialization.Encoding.PEM))
            if expired:
                discarded=parent.with_name('.'+parent.name+'-expired-'+str(uuid.uuid4()))
                os.rename(parent,discarded)
                for path in discarded.iterdir():path.unlink()
                discarded.rmdir()
            os.replace(staging,parent);fsync_dir(parent.parent)
        finally:
            if staging.exists():shutil.rmtree(staging)
        data=trust.read();trust.event(data,'certificate.rotated' if expired else 'certificate.created',fingerprint=fingerprint(cert));trust.save(data)
        rotation=data['events'][-1] if expired else None
        LOG.warning('Local TLS certificate rotated; peer approval required' if expired else 'Local TLS certificate created; peer approval required')
        return {**public_info(cert),**({'rotation_event':rotation} if rotation else {})}


def server_context(config):
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(config.cert,config.key);context.verify_mode=ssl.CERT_OPTIONAL
    context.verify_flags|=ssl.VERIFY_X509_PARTIAL_CHAIN
    refresh_context(config,context)
    return context


def refresh_context(config,context):
    pin=Trust(config).pin()
    if pin and getattr(context,'hemlock_pin',None)!=pin['certificate']:
        cert=parse_certificate(base64.b64decode(pin['certificate']))
        context.load_verify_locations(cadata=cert.public_bytes(serialization.Encoding.PEM).decode())
        context.hemlock_pin=pin['certificate']


def authorize_client(config,der):
    pin=Trust(config).pin()
    if not pin or not der:raise TLSFailure('peer_approval_required','Peer approval required')
    cert=parse_certificate(der);valid_now(cert)
    if fingerprint(cert)!=pin['fingerprint']:raise TLSFailure('peer_pin_changed','Peer certificate differs from approved SPKI')


def introduction(config,client_der=None):
    info=own_info(config)
    info['approved_peer']=None
    pin=Trust(config).pin()
    if pin:info['approved_peer']={'node_id':pin['node_id'],'fingerprint':pin['fingerprint']}
    return info


class PinnedConnection(http.client.HTTPSConnection):
    def __init__(self,config,*,pin=None,client=False):
        self.tls_config=config;self.pin=pin
        url=urlsplit(config.peer_url)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # This dedicated socket authenticates SPKI in connect(), never CA fallback.
        context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        if client:context.load_cert_chain(config.cert,config.key)
        super().__init__(url.hostname,url.port or 443,timeout=config.timeout,context=context)
    def connect(self):
        try:
            super().connect();self.der=self.sock.getpeercert(binary_form=True)
            cert=parse_certificate(self.der);valid_now(cert)
            if self.pin and fingerprint(cert)!=self.pin['fingerprint']:
                raise TLSFailure('peer_pin_changed','Peer certificate differs from approved SPKI; new approval required')
        except BaseException:
            self.close();raise


def read_public(connection,config):
    # Only this fixed public endpoint is requested before approval/authentication.
    connection.request('GET','/tls/introduction',headers={'Accept':'application/json'})
    response=connection.getresponse();raw=response.read(LIMIT+1)
    if response.status!=200 or len(raw)>LIMIT:raise TLSFailure('tls_introduction_failed','Peer does not provide a bounded TLS introduction')
    try:
        data=json.loads(raw);cert=parse_certificate(connection.der)
        if (not isinstance(data,dict) or not isinstance(data.get('node_id'),str) or len(data['node_id'])>128
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',data['node_id'])
                or data.get('fingerprint')!=fingerprint(cert)):raise ValueError()
        approved=data.get('approved_peer')
        if approved is not None and (not isinstance(approved,dict) or set(approved)!={'node_id','fingerprint'}
            or not isinstance(approved['node_id'],str) or len(approved['node_id'])>128
            or not isinstance(approved['fingerprint'],str) or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}',approved['fingerprint'])):raise ValueError()
        return {'node_id':data['node_id'],**public_info(cert),'certificate':base64.b64encode(connection.der).decode(),
                'approved_peer':data.get('approved_peer')}
    except (ValueError,TypeError,KeyError):raise TLSFailure('tls_introduction_failed','Invalid peer TLS introduction') from None


def discover(config):
    connection=PinnedConnection(config)
    try:return read_public(connection,config)
    except (OSError,ssl.SSLError,http.client.HTTPException):raise TLSFailure('peer_unavailable','Peer TLS introduction unavailable') from None
    finally:connection.close()


def verify_mutual(config):
    """Inbound data also requires the configured peer's independent approval."""
    pin=Trust(config).pin()
    if not pin:raise TLSFailure('peer_approval_required','Peer approval required')
    connection=PinnedConnection(config,pin=pin)
    try:
        connection.connect();remote=read_public(connection,config);own=own_info(config)
        if remote['node_id']!=config.peer_node_id:raise TLSFailure('peer_identity_mismatch','Claimed peer node ID differs from expected node ID')
        if remote.get('approved_peer')!={'node_id':config.node_id,'fingerprint':own['fingerprint']}:
            raise TLSFailure('remote_approval_required','Peer approval required on the other node')
    except (OSError,http.client.HTTPException):raise TLSFailure('peer_unavailable','Mutual peer approval cannot currently be confirmed') from None
    finally:connection.close()


class Reply:
    def __init__(self,response,connection,url):self.response=response;self.connection=connection;self.headers=response.headers;self.url=url
    def read(self,*args):return self.response.read(*args)
    def geturl(self):return self.url
    def close(self):self.response.close();self.connection.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class PinnedOpener:
    def __init__(self,config):self.config=config
    def open(self,request,timeout=None):
        config=self.config;trust=Trust(config);pin=trust.pin()
        if not pin:
            trust.discover()
            raise TLSFailure('peer_approval_required','Peer approval required')
        # Observe remote approval without credentials or a client certificate.
        observed=trust.discover()
        if observed['fingerprint']!=pin['fingerprint']:raise TLSFailure('peer_pin_changed','Peer certificate differs from approved SPKI; new approval required')
        if observed['node_id']!=config.peer_node_id:raise TLSFailure('peer_identity_mismatch','Claimed peer node ID differs from expected node ID')
        own=own_info(config)
        if observed.get('approved_peer')!={'node_id':config.node_id,'fingerprint':own['fingerprint']}:
            raise TLSFailure('remote_approval_required','Peer approval required on the other node')
        connection=PinnedConnection(config,pin=pin,client=True)
        try:
            # Pin and remote approval are checked again on the actual data socket.
            connection.connect();actual=read_public(connection,config)
            if actual['node_id']!=config.peer_node_id or actual.get('approved_peer')!={'node_id':config.node_id,'fingerprint':own['fingerprint']}:
                raise TLSFailure('remote_approval_required','Mutual peer approval is required')
            url=urlsplit(request.full_url);expected=urlsplit(config.peer_url)
            if (url.scheme,url.hostname,url.port)!=(expected.scheme,expected.hostname,expected.port):raise TLSFailure('tls_target_invalid','Replication target differs from configured peer')
            connection.request(request.get_method(),url.path+('?' + url.query if url.query else ''),body=request.data,headers=dict(request.header_items()))
            response=connection.getresponse();reply=Reply(response,connection,request.full_url)
            if response.status>=400:raise HTTPError(request.full_url,response.status,'Peer rejected request',response.headers,reply)
            if 300<=response.status<400:raise TLSFailure('tls_redirect','Replication redirects are forbidden')
            return reply
        except HTTPError:raise
        except BaseException:connection.close();raise


class Lifecycle:
    def __init__(self,config,notifications,restart,context=None,rotation=None):
        self.config=config;self.notifications=notifications;self.restart=restart;self.context=context;self.rotation=rotation
    def step(self):
        if self.context:refresh_context(self.config,self.context)
        info=own_info(self.config);remaining=info['not_after']-time.time()
        trust=Trust(self.config)
        with trust.locked():
            data=trust.read();key=info['fingerprint']+':'+str(info['not_after'])
            if remaining>0 and remaining<=self.config.tls_warn_days*86400 and key not in data['warned']:
                data['warned'].append(key);trust.event(data,'certificate.expiring',fingerprint=info['fingerprint']);trust.save(data)
                LOG.warning('Local TLS certificate expires soon; planned rotation will require peer approval')
                self.notifications.submit('Hemlock TLS certificate expiring',f'Node: {self.config.node_id}\nExpiry: {datetime.fromtimestamp(info["not_after"],UTC).isoformat()}\nRotation requires peer approval.')
        if self.rotation:
            event=self.rotation;self.rotation=None
            self.notifications.submit('Hemlock TLS certificate rotated',f'Node: {self.config.node_id}\nTime: {datetime.fromtimestamp(event["at"],UTC).isoformat()}\nPeer approval required.')
        if remaining<=0:
            LOG.warning('TLS certificate expired; gracefully restarting HTTPS only')
            self.restart()
