"""Read-only, bounded presentation models; routing/replication decisions stay elsewhere."""
import ipaddress
import json
import time
from .domain import Invalid, desired, prefix
from .observations import volatile
from .protocol import confirmed


def paginate(items, number, size):
    if number < 1 or not 1 <= size <= 100:
        raise Invalid('Invalid pagination')
    number = min(number, max(1, (len(items)+size-1)//size))
    return {'items':items[(number-1)*size:number*size], 'total':len(items), 'page':number, 'size':size}


def source(rule):
    return f"AS{rule['asn']} — {rule['name'] or 'Name unknown'}" if rule['kind']=='asn' else 'Blocked from IP networks list'


class View:
    def __init__(self, service, now=None):
        self.service, self.config = service, service.config
        self.now = time.time() if now is None else now
        from .transition import RoleTransition, TERMINAL
        self.transition = RoleTransition(self.config).status()
        self.transition_pending = bool(self.transition and self.transition['phase'] not in TERMINAL)
        with service.store.connect() as db:
            db.execute('BEGIN')
            self.rules = {r['id']:r for r in (json.loads(row[0]) for row in db.execute("SELECT body FROM documents WHERE kind='rule' ORDER BY id"))}
            self.local = {row[0]:json.loads(row[1]) for row in db.execute('SELECT key,body FROM local') if not row[0].startswith('login-limit:') and not volatile(row[0])}
            self.local.update(service.store.observations.snapshot())
            self.info = {key:service.store.meta(db,key) for key in ('history','sequence','master_id')}
            self.info['sequence'] = int(self.info['sequence'] or 0)
            self.protection = service.protection(db)
            self.routes, self.excluded = desired(self.rules.values(),self.protection)
        self.rib = self.local.get('rib') or {}
        self.bgp = self.local.get('bgp') or {}
        attempt = self.local.get('worker:observation') or {}
        self.rib_known = bool(self.rib.get('at')) and not self.transition_pending and not (attempt.get('error') and attempt.get('at',0)>self.rib['at'])
        self.rib_stale = bool(self.rib.get('at')) and self.now-self.rib['at']>45
        self.rib_fresh = self.rib_known and not self.rib_stale
        self.by_prefix = {}
        for p in self.rib.get('paths',[]):
            self.by_prefix.setdefault(p['prefix'],[]).append(p)
        self.sources = {}
        for rule in self.rules.values():
            for candidate in rule['prefixes']:
                self.sources.setdefault(candidate,[]).append(rule)
        self.exclusions = {(e['prefix'],e['rule_id']):e['reason'] for e in self.excluded}

    def attributes(self, candidate):
        ipv6 = ':' in candidate
        return {'next_hop':self.config.v6_next_hop if ipv6 else self.config.v4_next_hop,
                'local_preference':self.config.v6_local_pref if ipv6 else self.config.local_pref,
                'communities':[self.config.v6_community if ipv6 else self.config.community]}

    def applied(self, candidate):
        attrs = self.attributes(candidate)
        return candidate in self.routes and bool(attrs['next_hop']) and any(
            p.get('local') and tuple(p.get('owner',[]))==self.config.owner and
            p.get('next_hop')==attrs['next_hop'] and p.get('local_pref')==attrs['local_preference'] and
            sorted(p.get('communities',[]))==sorted(attrs['communities'])
            for p in self.by_prefix.get(candidate,[]))

    def route_state(self, candidate):
        if candidate not in self.routes:
            return 'Excluded by protection'
        if not self.rib_fresh:
            return 'Stale' if self.rib_stale else 'Unknown'
        if self.applied(candidate):
            return 'Applied'
        if self.bgp.get('error') or not self.attributes(candidate)['next_hop']:
            return 'Failed'
        return 'Pending'

    def origin(self, rule, candidate):
        return {'source':source(rule),'comment':rule['comment'],'author':rule['author'],'added':rule['created'],
                'excluded_reason':self.exclusions.get((candidate,rule['id']))}

    def peers(self):
        result=[]
        states={1:'Idle',2:'Connect',3:'Active',4:'OpenSent',5:'OpenConfirm',6:'Established'}
        for p in self.rib.get('peers',[]):
            status=('Stale' if self.rib_stale else 'Unknown') if not self.rib_fresh else ('Disabled' if p.get('admin_state') in (2,3) else states.get(p.get('session_state'),'Unknown'))
            export=self.rib.get('export',{}).get(p['address'],{})
            known=self.rib_fresh and p.get('session_state')==6 and not export.get('error') and not export.get('truncated') and 'prefixes' in export
            result.append({'peer':p.get('description') or p['address'], 'address':p['address'], 'status':status,
                           'uptime_seconds':max(0,self.now-p['established_at']) if status=='Established' and p.get('established_at') else None,
                           'ipv4_advertised':sum(':' not in n for n in set(export['prefixes'])) if known else None,
                           'ipv6_advertised':sum(':' in n for n in set(export['prefixes'])) if known else None})
        return result

    def dashboard(self):
        peer=self.local.get('peer') or {};sync=self.local.get('sync') or {};ack=self.local.get('peer_ack') or {}
        fresh=bool(peer.get('at')) and self.now-peer['at']<=max(15,self.config.poll_seconds*5)
        failure=self.local.get('worker:replication') or {}
        worker_failed=bool(failure.get('error')) and failure.get('at',0)>sync.get('at',0)
        success=sync.get('last_success') or (sync.get('at') if sync.get('ok') else None)
        if not self.config.peer_url:
            status='Not configured';lag=None
        elif sync.get('code') in ('protocol_mismatch','peer_upgrade_required','handshake_required','peer_auth_failed'):
            status={'protocol_mismatch':'Protocol version mismatch','peer_upgrade_required':'Peer upgrade required',
                    'handshake_required':'Handshake required','peer_auth_failed':'Authentication failed'}[sync['code']];lag=None
        elif sync.get('code')=='two_masters':
            status='Conflict: two masters';lag=None
        elif not fresh or not sync.get('ok') or worker_failed:
            status='Unavailable' if not peer.get('at') else 'Stale / unavailable';lag=None
        elif not confirmed(self.service.store,self.now):
            status='Handshake required';lag=None
        else:
            remote=peer.get('status') or {}
            same=remote.get('history')==self.info['history']
            lag=max(0,(self.info['sequence']-int(remote.get('sequence',0))) if self.config.role=='master' else (int(remote.get('sequence',0))-self.info['sequence'])) if same else None
            status='In sync' if same and lag==0 else 'Catching up'
        counts=lambda values:{'ipv4':sum(':' not in p for p in values),'ipv6':sum(':' in p for p in values),'total':len(values)}
        applied={p for p in self.routes if self.applied(p)} if self.rib_fresh else None
        failed={p for p in self.routes if self.route_state(p)=='Failed'} if self.rib_fresh else None
        pending={p for p in self.routes if self.route_state(p)=='Pending'} if self.rib_fresh else None
        withdrawals={p['prefix'] for p in self.rib.get('paths',[]) if p.get('local') and tuple(p.get('owner',[]))==self.config.owner and p['prefix'] not in self.routes} if self.rib_fresh else set()
        protection=self.local.get('protection') or {}
        ready=all(str(a) in protection.get('success',{}) for a in self.config.protected_asns)
        errors=[]
        if self.transition_pending:
            errors.append('Role transition cleanup pending; route application is fenced. ' + (self.transition.get('error') or ''))
        if not ready:errors.append('Protection initialization incomplete; new announcements are blocked.')
        errors.extend(v['error'] for v in (self.local.get('protection_schedule') or {}).values() if v.get('error'))
        if self.bgp.get('error'):errors.append(self.bgp['error'])
        return {'role_transition':self.transition,'peer':{'name':self.config.peer_node_id,'status':status,'healthy':status=='In sync','last_success':success,'lag':lag,'compatibility':self.local.get('peer_compatibility') or {}},
                'blocked':counts(applied) if applied is not None else None,'required':counts(self.routes),
                'pending':len(pending)+len(withdrawals) if pending is not None else None,'withdrawals':len(withdrawals),'failed':len(failed) if failed is not None else None,
                'excluded':len({e['prefix'] for e in self.excluded}),
                'application_status':'Fresh' if self.rib_fresh else ('Stale' if self.rib_stale else 'Unknown'),
                'errors':list(dict.fromkeys(errors)),'peers':self.peers(),'observed_at':self.rib.get('at')}

    def route_page(self, q='', ip='', number=1, size=25, sort='prefix', direction='asc'):
        if sort not in ('prefix','source','comment','added') or direction not in ('asc','desc'):
            raise Invalid('Invalid route sort')
        try:address=ipaddress.ip_address(ip) if ip else None
        except ValueError as exc:raise Invalid('Search requires an IPv4 or IPv6 address') from exc
        candidates=[];query=q.casefold().strip()
        for candidate,rules in self.sources.items():
            net=ipaddress.ip_network(candidate)
            if address and (address.version!=net.version or address not in net):continue
            if query and query not in (candidate+' '+' '.join(source(r)+' '+r['comment'] for r in rules)).casefold():continue
            candidates.append(candidate)
        def network_key(p):
            net=ipaddress.ip_network(p)
            return net.version,int(net.network_address),net.prefixlen
        # Canonical network order is the stable tie-breaker in both directions.
        candidates.sort(key=network_key)
        def displayed_key(p):
            first=self.sources[p][0]
            if sort=='prefix':return network_key(p)
            if sort=='source':return source(first).casefold()
            if sort=='comment':return (first['comment'] or '—').casefold()
            return min(r['created'] for r in self.sources[p])
        candidates.sort(key=displayed_key,reverse=direction=='desc')
        page=paginate(candidates,number,size)
        page['items']=[{'prefix':p,'sources':[self.origin(r,p) for r in self.sources[p]],'state':self.route_state(p)} for p in page['items']]
        return page

    def detail(self, candidate):
        candidate=prefix(candidate)
        if candidate not in self.sources:raise Invalid('Prefix not found')
        export=[]
        for peer in self.peers():
            state=self.rib.get('export',{}).get(peer['address'],{})
            known=self.rib_fresh and peer['status']=='Established' and not state.get('error') and 'prefixes' in state
            present=candidate in state.get('prefixes',[])
            value=('Exported' if present else ('Unknown' if state.get('truncated') else 'Not exported')) if known else ('Stale' if self.rib_stale else 'Unknown')
            export.append({'peer':peer['peer'],'state':value})
        return {'prefix':candidate,'state':self.route_state(candidate),'sources':[self.origin(r,candidate) for r in self.sources[candidate]],
                'configured_attributes':self.attributes(candidate),
                'local_rib':bool(self.by_prefix.get(candidate)) if self.rib_fresh else None,
                'observed_attributes':[{'next_hop':p['next_hop'],'local_preference':p['local_pref'],'communities':p['communities']} for p in self.by_prefix.get(candidate,[])] if self.rib_fresh else [],
                'exports':export}


def rule_card(rule):
    result={k:v for k,v in rule.items() if k not in ('prefixes','pending','id')}
    result['id']=rule['id']
    result['prefix_count']=len(rule['prefixes'])
    result['prefix']=rule['prefixes'][0] if rule['kind']=='manual' else None
    result['pending']={k:v for k,v in rule['pending'].items() if k!='prefixes'}|{'count':len(rule['pending']['prefixes'])} if rule.get('pending') else None
    return result


ACTIONS={'rule.batch':'Batch results','audit.prune':'Audit retention batch','notification.failed':'Notification failed','system.error':'Background operation failed','security.suspicious':'Suspicious access','rule.create':'Rule added','rule.import':'Rules imported','rule.delete':'Rule removed','rule.comment':'Comment updated',
         'asn.refresh':'ASN refreshed','asn.confirm':'ASN update confirmed','user.update':'User updated','auth.login':'Sign in',
         'auth.logout':'Sign out','auth.password':'Password changed','user.reset-password':'Password reset','user.create':'User created',
         'routes.withdraw-owned':'Owned routes withdrawn','auth.session':'Session check','http.request':'Request'}
LABELS={'batch_id':'Batch','added':'Added','skipped':'Skipped','invalid':'Invalid','unconfirmed':'Unconfirmed','reasons':'Reasons','window_seconds':'Window (seconds)','request_type':'Request type','count':'Events removed','plan_digest':'Retention plan digest','reason':'Failure reason','exit_code':'Exit code','asn':'ASN','name':'Name','comment':'Comment','author':'Added by','created':'Added','prefixes':'Prefixes',
        'origins':'Reference origins','last_success':'Last successful update','last_error':'Last error','next_update':'Next update',
        'pending':'Proposed update','role':'Role','enabled':'Enabled','kind':'Type','client_ip':'Client IP'}


def history_card(event):
    before=event.get('before') or {};after=event.get('after') or {};doc=after or before
    target=(source(doc) if doc.get('kind')=='asn' else (', '.join(doc.get('prefixes',[])[:2]) if doc.get('kind')=='manual' else doc.get('id','')))
    # Only account logins are user-facing identifiers; rule/audit UUIDs stay out.
    if not doc.get('kind') and 'role' not in doc:target=event['object'].split(':')[0]
    def value(key,item):
        if item is None:return '—'
        if key=='reasons':
            return ', '.join(f"{reason.replace('_',' ')}: {count}" for reason,count in sorted(item.items())) or 'None'
        if key=='prefixes':return f'{len(item)} prefixes'+(': '+', '.join(item[:3])+(' …' if len(item)>3 else '') if item else '')
        if key=='pending':return f"{len(item['prefixes'])} prefixes awaiting confirmation"
        if key=='origins':return ', '.join(f"AS{o['asn']}" for o in item) or 'Unknown'
        if key in ('created','last_success','next_update'):return {'timestamp':item}
        if isinstance(item,bool):return 'Yes' if item else 'No'
        return str(item)
    return {'at':event['at'],'node':event['node'],'actor':event['actor'],'action':ACTIONS.get(event['action'],'Operation'),
            'target':target,'result':event['result'].capitalize(),
            'changes':[{'field':title,'before':value(key,before.get(key)),'after':value(key,after.get(key))} for key,title in LABELS.items() if before.get(key)!=after.get(key)]}


def protection_page(service, kind='summary', q='', number=1, size=25):
    """Only loaded protection settings and retained prefixes; no config secrets."""
    with service.store.connect() as db:
        db.execute('BEGIN')
        row=db.execute("SELECT body FROM local WHERE key='protection'").fetchone()
        cached=json.loads(row[0]) if row else {}
    configured={prefix(p) for p in service.config.protected_prefixes}
    retained={prefix(p) for p in cached.get('prefixes',[])}
    numbers=sorted(set(service.config.protected_asns))
    summary={'node_id':service.config.node_id,'asn_count':len(numbers),'prefix_count':len(configured|retained)}
    if kind=='summary':return summary
    query=q.strip().casefold()
    if kind=='asns':
        items=[{'asn':a,'last_success':cached.get('success',{}).get(str(a))} for a in numbers if not query or query in f'AS{a}'.casefold()]
    elif kind=='prefixes':
        def key(p):
            net=ipaddress.ip_network(p)
            return net.version,int(net.network_address),net.prefixlen
        items=[{'prefix':p,'sources':(['configuration'] if p in configured else [])+(['cache'] if p in retained else [])}
               for p in sorted(configured|retained,key=key) if not query or query in p.casefold()]
    else:raise Invalid('Unknown protection list')
    return summary|paginate(items,number,size)
