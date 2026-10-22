"""FastAPI endpoints; all replicated mutations go through the shared service."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import time

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .auth import Auth, password_hash, PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH
from .domain import Conflict, Forbidden, Invalid, NeedSnapshot
from .irr import Metadata
from .reconcile import Reconciler
from .replication import PeerTransport, Replicator
from .service import Service
from .store import Store, redact
from .workers import ASNWorker, ProtectionWorker, process_lock, repeat


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Body):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class NewRule(Body):
    value: str = Field(min_length=1, max_length=100)
    comment: str = Field(default='', max_length=10000)


class BatchRules(Body):
    value: str
    comment: str = Field(default="", max_length=10000)


class Comment(Body):
    comment: str = Field(max_length=10000)


class ImportRules(Body):
    items: list[NewRule] = Field(min_length=1, max_length=1000)


class Confirm(Body):
    digest: str = Field(min_length=64, max_length=64)


class UserChange(Body):
    role: str | None = None
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class Password(Body):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


def create_app(config, *, adapter=None, background=True, observations=None,
               replication_protocol_version=None):
    @asynccontextmanager
    async def lifespan(app):
        with process_lock(config.database):
            from .transition import RoleTransition
            startup_adapter = adapter
            if startup_adapter is None:
                from .gobgp import GoBGP
                startup_adapter = GoBGP(config)
            try:
                await asyncio.to_thread(RoleTransition(config).prepare, startup_adapter)
            finally:
                if adapter is None:startup_adapter.close()
            store = Store(config, observations=observations)
            from .notifications import Notifications
            from .retention import RetentionWorker
            notifications = Notifications(store)
            store.notifications = notifications
            store.on_commit = notifications.committed
            service = Service(store)
            auth = Auth(store)
            from .protocol import Gate, REPLICATION_PROTOCOL_VERSION
            from .installed import application_identity
            version=REPLICATION_PROTOCOL_VERSION if replication_protocol_version is None else replication_protocol_version
            store.replication_protocol_version=version
            app.state.replication_gate=Gate(store,version,application_identity()['version'])
            peer = PeerTransport(config,protocol_version=version)
            asn_worker = ASNWorker(service)
            app.state.store, app.state.service, app.state.auth = store, service, auth
            app.state.peer, app.state.asn_worker = peer, asn_worker
            app.state.metadata = Metadata(config)
            local_adapter = adapter
            if local_adapter is None:
                from .gobgp import GoBGP
                local_adapter = GoBGP(config, lambda candidate: service.protection().check(candidate))
            app.state.adapter = local_adapter
            notifications.start()
            stop = asyncio.Event()
            tasks = []
            if background:
                work = [(RetentionWorker(store).step, 30, 'retention'),
                        (asn_worker.step, 30, 'asn'),
                        (ProtectionWorker(service).step, 60, 'protection'),
                        (Reconciler(service, local_adapter).step, 3, 'bgp'),
                        (lambda: observe_bgp(store, local_adapter), 15, 'observation')]
                if config.peer_url:
                    work.append((Replicator(store, peer).step, config.poll_seconds, 'replication'))
                tasks = [asyncio.create_task(repeat(stop, fn, interval, store, name)) for fn, interval, name in work]
            try:
                yield
            finally:
                stop.set()
                await asyncio.gather(*tasks)
                await asyncio.to_thread(notifications.close)
                if hasattr(local_adapter, 'close'):
                    local_adapter.close()
    app = FastAPI(title='Hemlock', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    static = Path(__file__).parent / 'static'
    app.mount('/static', StaticFiles(directory=static), name='static')

    def record_http_failure(request, status):
        if status < 400:
            return
        actor = getattr(request.state, 'actor', None)
        if actor is None:
            try:
                actor, _ = app.state.auth.session(request.cookies.get('hemlock_session', ''))
            except Forbidden:
                pass
        expected_validation = actor and actor.role == 'admin' and (status in (400, 409, 413, 415, 422) or getattr(request.state, 'expected_validation', False))
        if not expected_validation and status in (400,401,403,404,405,413,415,422,429) and request.client:
            app.state.store.notifications.suspicious(request.client.host, 'unauthorized_request' if status in (401,403) else 'invalid_request')
        if getattr(request.state, 'hemlock_audited', False):
            return
        # The route category is fixed. Never persist URL/query/body/header values.
        path = request.url.path
        action, object_name = 'http.request', 'request'
        if path.startswith('/api/rules'):
            action, object_name = 'rule.create', 'rule'
        elif path.startswith('/api/users'):
            action, object_name = 'user.update', 'user'
        elif path == '/api/password':
            action, object_name = 'auth.password', 'user'
        elif path in ('/api/me', '/api/logout'):
            action, object_name = 'auth.session', 'session'
        elif path == '/api/login':
            action, object_name = 'auth.login', 'session'
        result = 'failed' if status >= 500 else 'denied' if status in (401, 403) else 'invalid'
        app.state.store.security_event(actor.login if actor else 'anonymous', action, object_name, result)
        request.state.hemlock_audited = True

    @app.middleware('http')
    async def safety(request, call_next):
        response = None
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            chunks, received = [], 0
            async for chunk in request.stream():
                received += len(chunk)
                if received > config.request_max_bytes:
                    response = JSONResponse({'error':f'Request exceeds {config.request_max_bytes} bytes; nothing saved'}, status_code=413)
                    break
                chunks.append(chunk)
            if response is None:
                request._body = b''.join(chunks)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            own_origin = str(request.base_url).rstrip('/')
            if response is not None:
                pass
            elif origin and origin != own_origin:
                response = JSONResponse({'error': 'Cross-origin mutation rejected'}, status_code=403)
            elif request.headers.get('sec-fetch-site') == 'cross-site':
                response = JSONResponse({'error': 'Cross-site mutation rejected'}, status_code=403)
            elif request.headers.get('content-type', '').split(';')[0] != 'application/json':
                response = JSONResponse({'error': 'JSON content type required'}, status_code=415)
        if response is None:
            try:
                response = await call_next(request)
            except Exception as exc:
                # Do not expose exception strings that may contain credentials.
                request.state.hemlock_audited = getattr(exc, 'hemlock_audited', False)
                response = JSONResponse({'error': 'Request failed; check local service health'}, status_code=500)
        try:
            await asyncio.to_thread(record_http_failure, request, response.status_code)
        except Exception:
            response = JSONResponse({'error': 'Security audit storage unavailable'}, status_code=503)
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        if getattr(request.state,'replication_headers',None):
            response.headers.update(request.state.replication_headers)
        return response

    from .protocol import ProtocolFailure

    @app.exception_handler(ProtocolFailure)
    async def protocol_failure(request,exc):
        return JSONResponse({'error':str(exc),'code':exc.code,**exc.details},
                            status_code={'peer_upgrade_required':426,'protocol_mismatch':412,'handshake_required':428}[exc.code])

    @app.exception_handler(Forbidden)
    async def forbidden(request, exc):
        if str(exc).startswith('Protected ASN') or ' is inside protected ' in str(exc):
            request.state.expected_validation = True
        request.state.hemlock_audited = getattr(exc, 'hemlock_audited', False)
        return JSONResponse({'error': str(exc), **({'session_required':True} if str(exc) in ('Login required','Session expired','Session revoked') else {})}, status_code=403)

    @app.exception_handler(Invalid)
    async def invalid(request, exc):
        request.state.hemlock_audited = getattr(exc, 'hemlock_audited', False)
        return JSONResponse({'error': str(exc)}, status_code=422)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        request.state.hemlock_audited = getattr(exc, 'hemlock_audited', False)
        return JSONResponse({'error': str(exc), **({'existing_rule_id': exc.rule_id} if hasattr(exc, 'rule_id') else {})}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def validation(request, exc):
        # Validation error inputs may contain passwords; do not serialize them.
        return JSONResponse({'error': 'Invalid request fields or field lengths'}, status_code=422)

    def current(request: Request):
        actor = request.app.state.auth.session(request.cookies.get('hemlock_session', ''))[0]
        request.state.actor = actor
        return actor

    def mutation(request: Request):
        actor, csrf = request.app.state.auth.session(request.cookies.get('hemlock_session', ''))
        request.state.actor = actor
        if not secrets.compare_digest(request.headers.get('x-csrf-token', '').encode(), csrf.encode()):
            raise Forbidden('CSRF validation failed')
        return actor

    def peer_auth(request: Request):
        if not request.app.state.peer.authorized(request.headers.get('authorization'), request.headers.get('x-hemlock-node')):
            raise Forbidden('Peer authentication required')

    def exchange_auth(request: Request):
        peer_auth(request)
        request.state.replication_headers=app.state.replication_gate.require(request.headers)
        if 'protocol' in request.query_params:
            raise Invalid('Obsolete format selector; only the negotiated replication protocol is accepted')

    def page(items, q, page, size):
        if page < 1 or not 1 <= size <= 100:
            raise Invalid('Invalid pagination')
        if q:
            from .store import encode
            items = [item for item in items if q.lower() in encode(item).lower()]
        from .presentation import paginate
        return paginate(items, page, size)

    @app.get('/')
    def index():
        return FileResponse(static / 'index.html')

    @app.post('/api/login')
    def login(body: Login, request: Request):
        token, csrf = app.state.auth.login(body.login, body.password, request.client.host if request.client else '')
        response = JSONResponse({'csrf': csrf})
        response.set_cookie('hemlock_session', token, httponly=True, secure=config.tls, samesite='strict', max_age=8*3600, path='/')
        return response

    @app.get('/api/session')
    def session_status(request: Request):
        try:
            app.state.auth.session(request.cookies.get('hemlock_session', ''))
            return {'authenticated':True}
        except Forbidden:
            return {'authenticated':False}

    @app.get('/api/me')
    def me(request: Request, actor=Depends(current)):
        from .installed import application_identity
        _, csrf = app.state.auth.session(request.cookies.get('hemlock_session', ''))
        return {'login': actor.login, 'role': actor.role, 'node_role': config.role, 'node_id': config.node_id, 'csrf': csrf,
                'password_change_node': config.node_id if config.role=='master' else config.peer_node_id,
                'batch_max_items':config.batch_max_items, 'request_max_bytes':config.request_max_bytes,
                'application':application_identity()}

    @app.post('/api/logout')
    def logout(request: Request, actor=Depends(mutation)):
        app.state.auth.logout(request.cookies.get('hemlock_session', ''))
        response = JSONResponse({'ok': True})
        response.delete_cookie('hemlock_session', path='/', secure=config.tls, httponly=True, samesite='strict')
        return response

    @app.post('/api/password')
    def change_password(body: Password, actor=Depends(mutation)):
        with app.state.store.connect() as db:
            app.state.store.require_master(db)
        user = app.state.store.get('user', actor.login)
        from .auth import password_verify
        if not password_verify(user['password_hash'], body.current_password):
            raise Forbidden('Current password is incorrect')
        app.state.service.save_user(actor, actor.login, password_hash=password_hash(body.new_password), own=True,
                                    expected_version=user['version'])
        return {'status': 'saved', 'session': 'revoked'}

    @app.get('/api/rules')
    def rules(kind: str = '', q: str = '', page_number: int = 1, size: int = 25, actor=Depends(current)):
        items = app.state.store.list('rule')
        if kind:
            if kind not in ('asn', 'manual'):
                raise Invalid('Unknown rule kind')
            items = [r for r in items if r['kind'] == kind]
        return page(items, q, page_number, size)

    @app.post('/api/rules/manual')
    def add_manual(body: NewRule, actor=Depends(mutation)):
        app.state.service.writable(actor)
        from .domain import prefix
        candidate = prefix(body.value)
        app.state.service.protection().check(candidate)
        try:
            origins = app.state.metadata.origins(candidate)
        except Exception:
            origins = []
        return {'status': 'saved', 'rule': app.state.service.add_manual(actor, candidate, body.comment, origins)}

    @app.post('/api/coverage/batch')
    def batch_coverage(body: BatchRules, actor=Depends(mutation)):
        import re
        from .coverage import index_for
        from .presentation import View
        from .domain import prefix
        values = [v.strip() for v in re.split(r'[,\n\r]',body.value) if v.strip()]
        if not 1 <= len(values) <= config.batch_max_items:
            raise Invalid(f'Batch requires 1..{config.batch_max_items} elements')
        index = index_for(View(app.state.service))
        items, covered, invalid = [], 0, 0
        protection = app.state.service.protection()
        for raw in values:
            try:
                value = prefix(raw)
                badges = index.summary(value)
                if badges:
                    covered += 1
                if len(items) < 25:
                    items.append({'prefix':value,'badges':badges,'error':protection.reason(value)})
            except Invalid as exc:
                invalid += 1
                if len(items) < 25:
                    items.append({'prefix':raw[:100],'badges':[],'error':str(exc)[:200]})
        return {'items':items,'total':len(values),'covered':covered,'invalid':invalid}

    @app.post('/api/rules/manual-batch')
    def manual_batch(body: BatchRules, actor=Depends(mutation)):
        from .batch import add
        return add(app.state.service, actor, body.value, body.comment)

    @app.post('/api/rules/asn')
    def add_asn(body: NewRule, actor=Depends(mutation)):
        rule = app.state.service.add_asn(actor, body.value, body.comment)
        rule = app.state.asn_worker.refresh(actor, rule['id'])
        return {'status': 'saved', 'rule': rule}

    @app.post('/api/rules/import')
    def import_rules(body: ImportRules, actor=Depends(mutation)):
        items = [item.model_dump() for item in body.items]
        return {'status': 'saved', 'rules': app.state.service.import_manual(actor, items)}

    @app.patch('/api/rules/{rule_id}')
    def comment(rule_id: str, body: Comment, actor=Depends(mutation)):
        return {'status': 'saved', 'rule': app.state.service.update_comment(actor, rule_id, body.comment)}

    @app.delete('/api/rules/{rule_id}')
    def delete_rule(rule_id: str, actor=Depends(mutation)):
        app.state.service.delete_rule(actor, rule_id)
        return {'status': 'saved'}

    @app.post('/api/rules/{rule_id}/refresh')
    def refresh(rule_id: str, actor=Depends(mutation)):
        return {'status': 'saved', 'rule': app.state.asn_worker.refresh(actor, rule_id)}

    @app.post('/api/rules/{rule_id}/confirm')
    def confirm(rule_id: str, body: Confirm, actor=Depends(mutation)):
        return {'status': 'saved', 'rule': app.state.service.confirm_asn(actor, rule_id, body.digest)}

    @app.get('/api/info/protection')
    def info_protection(kind: str = 'summary', q: str = '', page_number: int = 1, size: int = 25, actor=Depends(current)):
        from .presentation import protection_page
        return protection_page(app.state.service,kind,q,page_number,size)

    @app.get('/api/dashboard')
    def dashboard(actor=Depends(current)):
        from .presentation import View
        return View(app.state.service).dashboard()

    @app.get('/api/routes')
    def route_list(q: str = '', ip: str = '', page_number: int = 1, size: int = 25, sort: str = 'prefix', direction: str = 'asc', actor=Depends(current)):
        from .presentation import View
        return View(app.state.service).route_page(q,ip,page_number,size,sort,direction)

    @app.get('/api/route-detail')
    def route_detail(prefix: str, actor=Depends(current)):
        from .presentation import View
        return View(app.state.service).detail(prefix)

    @app.get('/api/rule-cards')
    def rule_cards(kind: str = '', q: str = '', page_number: int = 1, size: int = 25, actor=Depends(current)):
        from .presentation import rule_card, View
        view=View(app.state.service)
        items=list(view.rules.values())
        if kind:
            if kind not in ('asn','manual'):raise Invalid('Unknown rule kind')
            items=[r for r in items if r['kind']==kind]
        if q:
            from .presentation import source
            items=[r for r in items if q.casefold() in (' '.join([source(r),str(r['asn'] or ''),r['comment'],r['author'],*r['prefixes']])).casefold()]
        result=page(items,'',page_number,size)
        from .coverage import index_for
        index=index_for(view)
        result['items']=[rule_card(r) | {'coverage': index.summary(r['prefixes'][0], r['id']) if r['kind']=='manual' else []} for r in result['items']]
        return result

    @app.get('/api/coverage')
    def coverage(value: str, rule_id: str = '', relation: str = '', page_number: int = 1, size: int = 25, actor=Depends(current)):
        from .presentation import View, paginate, rule_card
        from .coverage import index_for
        from .domain import prefix
        view=View(app.state.service)
        candidate=prefix(value)
        index=index_for(view)
        if relation:
            if relation not in ('asn','manual','contains'):raise Invalid('Unknown coverage relation')
            ids=index.related(candidate,rule_id)[relation]
            result=paginate(sorted(ids),page_number,size)
            result['items']=[rule_card(view.rules[key]) for key in result['items']]
            return result
        return {'badges':[] if view.protection.reason(candidate) else index.summary(candidate,rule_id)}

    @app.get('/api/rule-card/{rule_id}')
    def single_rule(rule_id: str, actor=Depends(current)):
        from .presentation import rule_card
        rule=app.state.store.get('rule',rule_id)
        if not rule:raise Invalid('Rule not found')
        return rule_card(rule)

    @app.get('/api/rules/{rule_id}/prefixes')
    def rule_prefixes(rule_id: str, proposal: bool = False, q: str = '', page_number: int = 1, size: int = 25, actor=Depends(current)):
        rule=app.state.store.get('rule',rule_id)
        if not rule:raise Invalid('Rule not found')
        values=(rule.get('pending') or {}).get('prefixes',[]) if proposal else rule['prefixes']
        if q:values=[p for p in values if q.lower() in p.lower()]
        return page(values,'',page_number,size)

    def history_page(actor, category, q, page_number, size, action, result, node, who, since, until):
        from .history import query
        return query(app.state.store, actor, category, q, page_number, size, action, result, node, who, since, until)

    @app.get('/api/history')
    def history(q: str = '', page_number: int = 1, size: int = 25, category: str = 'blocklist',
                action: str = '', result: str = '', node: str = '', who: str = '',
                since: float | None = None, until: float | None = None, actor=Depends(current)):
        from .presentation import history_card
        data = history_page(actor, category, q, page_number, size, action, result, node, who, since, until)
        data['items'] = [history_card(e) for e in data['items']]
        return data

    @app.get('/api/observation')
    def observation(ip: str = '', actor=Depends(current)):
        routes, excluded = app.state.service.routes()
        store = app.state.store
        info = store.info()
        peer = store.local('peer', {})
        peer['age_seconds'] = time.time() - peer['at'] if 'at' in peer else None
        peer['stale'] = peer['age_seconds'] is None or peer['age_seconds'] > max(15, config.poll_seconds * 5)
        ack = store.local('peer_ack', {})
        replicated = bool(config.role == 'master' and not peer['stale'] and ack.get('history') == info['history'] and ack.get('sequence') == info['sequence'])
        bgp = store.local('bgp')
        if bgp:
            bgp['age_seconds'] = time.time() - bgp['at']
            bgp['stale'] = (bgp['age_seconds'] > 15 or bgp.get('history') != info['history'] or bgp.get('sequence') != info['sequence'])
        rib = store.local('rib')
        if rib:
            rib['age_seconds'] = time.time() - rib['at']
            rib['stale'] = rib['age_seconds'] > 45
        from .transition import RoleTransition
        return {'role_transition':RoleTransition(config).status(),'local': info, 'peer': peer, 'sync': store.local('sync'), 'replicated': replicated,
                'replication': {'configured': bool(config.peer_url), 'peer_node_id': config.peer_node_id,
                                'status': 'configured' if config.peer_url else 'not_configured'},
                'announcements_enabled': config.announcements,
                'announcement_semantics': 'Disabled means zero route writes; existing routes remain. Use withdraw-owned maintenance to drain owned paths.',
                'desired': routes, 'excluded': excluded, 'bgp': bgp,
                'rib': rib, 'protection_ready': app.state.service.protection_ready(),
                'protection_schedule': store.local('protection_schedule'),
                'matches': app.state.service.search(ip) if ip else []}

    @app.get('/api/audit')
    def audit(q: str = '', page_number: int = 1, size: int = 25, category: str = 'blocklist', actor=Depends(current)):
        return history_page(actor, category, q, page_number, size, '', '', '', '', None, None)

    @app.get('/api/login-history')
    def login_history(login: str = '', actor=Depends(current)):
        login=login or actor.login
        if actor.role!='admin' and login!=actor.login:
            raise Forbidden('You may only view your own login history')
        from .presentation import View
        peer=View(app.state.service).dashboard()['peer']
        return {'login':login,'items':app.state.store.successful_logins(login),
                'peer':peer, 'scope':'Local and received peer events; peer history may lag synchronization.'}

    @app.get('/api/users')
    def users(q: str = '', page_number: int = 1, size: int = 25, actor=Depends(current)):
        actor.require_admin()
        return page([redact(u) for u in app.state.store.list('user')], q, page_number, size)

    @app.put('/api/users/{login}')
    def user_change(login: str, body: UserChange, actor=Depends(mutation)):
        app.state.service.writable(actor)
        hashed = password_hash(body.password) if body.password else None
        result = app.state.service.save_user(actor, login, role=body.role, enabled=body.enabled, password_hash=hashed)
        return {'status': 'saved', 'user': redact(result)}

    @app.get('/replication/handshake', dependencies=[Depends(peer_auth)])
    def handshake(request: Request):
        return app.state.replication_gate.handshake(request.headers)

    @app.get('/replication/status', dependencies=[Depends(exchange_auth)])
    def replication_status():
        from .transition import RoleTransition
        result = app.state.store.info() | app.state.replication_gate.identity()
        result['role_transition'] = RoleTransition(config).status()
        result['bgp'] = app.state.store.local('bgp')
        result['now'] = time.time()
        result['capabilities'] = ['audit-prune-v2']
        with app.state.store.connect() as db:
            result['security_history'] = app.state.store.meta(db, 'security_history')
            result['security_sequence'] = db.execute('SELECT COALESCE(MAX(seq),0) FROM security_audit').fetchone()[0]
            result['security_ack'] = {'history':app.state.store.meta(db, 'peer_security_history'), 'cursor':int(app.state.store.meta(db, 'peer_security_cursor', '0'))}
        return result

    @app.get('/replication/snapshot', dependencies=[Depends(exchange_auth)])
    def snapshot():
        with app.state.store.connect() as db:
            app.state.store.require_master(db)
        return app.state.store.snapshot()

    @app.get('/replication/events', dependencies=[Depends(exchange_auth)])
    def events(history: str, cursor: int):
        return app.state.store.events(history, cursor)

    @app.get('/replication/local-audit', dependencies=[Depends(exchange_auth)])
    def local_audit(after: int = 0, history: str = ''):
        if config.role != 'slave':
            raise Conflict('Only a slave exports pending local security events')
        return app.state.store.local_security_events(after=after, history=history)

    return app


def observe_bgp(store, adapter):
    result = adapter.observe()
    result['at'] = time.time()
    store.set_local('rib', result)
