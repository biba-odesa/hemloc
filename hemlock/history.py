"""SQL audit classification and bounded, authorization-aware history queries."""
import json
from .domain import Forbidden, Invalid

CATEGORIES = ('blocklist', 'users_access', 'errors_security')

# Legacy documents remain byte-for-byte unchanged. This expression is also indexed.
CATEGORY = """CASE
 WHEN json_extract(body,'$.action') IN ('rule.create','rule.import','rule.comment','rule.delete','asn.confirm')
      AND json_extract(body,'$.result')='saved' THEN 'blocklist'
 WHEN json_extract(body,'$.action')='asn.refresh' AND json_extract(body,'$.result')='saved'
      AND json_extract(body,'$.before.prefixes') IS NOT json_extract(body,'$.after.prefixes') THEN 'blocklist'
 WHEN json_extract(body,'$.action') IN ('user.create','user.update','user.reset-password','auth.login','auth.logout','auth.session','auth.password')
      THEN CASE WHEN json_extract(body,'$.actor')='anonymous' AND json_extract(body,'$.action')!='auth.login'
                AND json_extract(body,'$.result')!='success' THEN 'errors_security' ELSE 'users_access' END
 WHEN json_extract(body,'$.action') IN ('rule.batch','http.request','notification.failed','security.suspicious','system.error')
      OR (json_extract(body,'$.action') IN ('rule.create','rule.import','rule.comment','rule.delete','asn.refresh','asn.confirm','routes.withdraw-owned','audit.prune') AND json_extract(body,'$.result') IN ('denied','invalid','conflict','failed','throttled')) THEN 'errors_security'
 ELSE 'unknown' END"""

UNION = """SELECT id,body FROM documents WHERE kind='audit'
 UNION ALL SELECT id,body FROM security_audit s
 WHERE NOT EXISTS(SELECT 1 FROM documents d WHERE d.kind='audit' AND d.id=s.id)"""
VISIBLE = '(' + UNION + ") e WHERE NOT EXISTS(SELECT 1 FROM audit_tombstones t WHERE t.id=e.id)"


def setup(db):
    db.execute('CREATE TABLE IF NOT EXISTS audit_tombstones(id TEXT PRIMARY KEY, digest TEXT NOT NULL)')
    for table, suffix in (('documents', " WHERE kind='audit'"), ('security_audit', '')):
        db.execute(f'CREATE INDEX IF NOT EXISTS history_v2_{table} ON {table}(({CATEGORY}), json_extract(body,\'$.at\') DESC,id DESC)' + suffix)
        db.execute(f'DROP INDEX IF EXISTS history_{table}')


def query(store, actor, category='blocklist', q='', number=1, size=25, action='', result='', node='', who='', since=None, until=None):
    if category not in CATEGORIES + ('unknown',):
        raise Invalid('Unknown history category')
    if actor.role != 'admin' and category != 'blocklist':
        raise Forbidden('Only blocklist history is available to guests')
    if number < 1 or not 1 <= size <= 100 or len(q) > 256:
        raise Invalid('Invalid history pagination or search')
    predicates, params = [f'({CATEGORY})=?'], [category]
    for key, value in (('action', action), ('result', result), ('node', node), ('actor', who)):
        if value:
            predicates.append(f"json_extract(body,'$.{key}')=?")
            params.append(value)
    for operator, value in (('>=', since), ('<', until)):
        if value is not None:
            predicates.append(f"json_extract(body,'$.at'){operator}?")
            params.append(value)
    if q:
        # Search public audit fields, never serialized request content or hidden IDs.
        fields = ['action', 'actor', 'node', 'result', 'before.comment', 'after.comment', 'before.name', 'after.name', 'before.asn', 'after.asn', 'before.prefixes', 'after.prefixes']
        predicates.append('(' + ' OR '.join(f"instr(hemlock_fold(COALESCE(json_extract(body,'$.{f}'),'')),hemlock_fold(?))>0" for f in fields) + ')')
        params.extend([q] * len(fields))
        from .presentation import ACTIONS
        matched = [key for key, label in ACTIONS.items() if q.casefold() in label.casefold()]
        extras = ["instr(hemlock_fold('AS'||COALESCE(json_extract(body,'$.after.asn'),json_extract(body,'$.before.asn'),'')),hemlock_fold(?))>0"]
        params.append(q)
        if matched:
            extras.append("json_extract(body,'$.action') IN (" + ','.join('?' for _ in matched) + ')')
            params.extend(matched)
        predicates[-1] = '(' + predicates[-1] + ' OR ' + ' OR '.join(extras) + ')'
    sql = ' FROM ' + VISIBLE + ' AND ' + ' AND '.join(predicates)
    with store.connect() as db:
        db.create_function('hemlock_fold', 1, lambda value: str(value).casefold() if value is not None else '', deterministic=True)
        db.execute('BEGIN')
        total = db.execute('SELECT COUNT(*)' + sql, params).fetchone()[0]
        number = min(number, max(1, (total + size - 1)//size))
        rows = db.execute('SELECT body' + sql + " ORDER BY json_extract(body,'$.at') DESC,id DESC LIMIT ? OFFSET ?", params + [size, (number-1)*size]).fetchall()
    return {'items':[json.loads(r[0]) for r in rows], 'total':total, 'page':number, 'size':size}
