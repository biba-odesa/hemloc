"""Independent manual-rule commits with bounded batch reporting and one notification."""
import re
import time
import uuid

from .audit import audit_failures
from .domain import Duplicate, Forbidden, Invalid, prefix


class ProtectedInput(Forbidden):
    pass


@audit_failures('rule.import','rule')
def add(service, actor, value, comment=''):
    service.writable(actor)
    if not isinstance(value, str) or not isinstance(comment, str) or len(comment) > 10000:
        raise Invalid('Invalid batch fields')
    if len(value.encode('utf-8')) + len(comment.encode('utf-8')) > service.config.request_max_bytes:
        raise Invalid('Batch request exceeds request_max_bytes')
    inputs = [item.strip() for item in re.split(r'[,\n\r]', value) if item.strip()]
    if not 1 <= len(inputs) <= service.config.batch_max_items:
        raise Invalid(f'Batch requires 1..{service.config.batch_max_items} elements; nothing saved')
    result = {'batch_id':str(uuid.uuid4()), 'added':0, 'skipped':0, 'invalid':0,
              'unconfirmed':0, 'items':[], 'error':None, 'status':'complete'}
    seen, added = set(), []
    for index, raw in enumerate(inputs):
        item = {'input':raw, 'status':'invalid', 'reason':'invalid address/CIDR'}
        try:
            candidate = prefix(raw)
            item['prefix'] = candidate
        except Invalid as exc:
            item['reason'] = str(exc)[:200]
            item['code'] = 'invalid_cidr'
        else:
            if candidate in seen:
                item.update(status='skipped', reason='duplicate within batch', code='batch_duplicate')
            else:
                seen.add(candidate)
                try:
                    # Recheck protection within the same serialized write transaction.
                    doc = {'id':str(uuid.uuid4()), 'kind':'manual', 'asn':None, 'name':'',
                           'comment':comment, 'author':actor.login, 'created':time.time(),
                           'prefixes':[candidate], 'origins':[], 'last_success':None,
                           'last_error':'', 'next_update':None, 'pending':None}
                    def create(old):
                        # Store.change_many holds BEGIN IMMEDIATE on this thread.
                        reason = service.protection().reason(candidate)
                        if reason:
                            raise ProtectedInput(reason)
                        return doc
                    service.store.change_many(actor, 'rule.import', [('rule',doc['id'],create)],
                                              batch_id=result['batch_id'], notify=False)
                    item.update(status='added', reason='saved', code='saved', rule_id=doc['id'])
                    added.append(doc)
                except Duplicate as exc:
                    item.update(status='skipped', reason='existing duplicate', code='existing_duplicate', rule_id=exc.rule_id)
                except ProtectedInput:
                    seen.discard(candidate)
                    item.update(reason='protected network', code='protected')
                except Exception:
                    item.update(status='unconfirmed', reason='Infrastructure failure; save not confirmed', code='infrastructure')
                    result['error'] = 'Batch interrupted by a storage or node error; confirmed results are listed. Retry remaining input.'
                    result['status'] = 'interrupted'
        result['items'].append(item)
        if item['status'] == 'added':result['added'] += 1
        elif item['status'] == 'skipped':result['skipped'] += 1
        elif item['status'] == 'invalid':result['invalid'] += 1
        else:result['unconfirmed'] += 1
        if result['error']:
            for remaining in inputs[index+1:]:
                result['items'].append({'input':remaining, 'status':'unconfirmed', 'reason':'Not attempted after infrastructure failure', 'code':'not_attempted'})
                result['unconfirmed'] += 1
            break
    if result['skipped'] or result['invalid'] or result['unconfirmed']:
        reasons = {}
        for item in result['items']:
            if item['status'] != 'added':reasons[item['code']] = reasons.get(item['code'],0)+1
        context = {k:result[k] for k in ('batch_id','added','skipped','invalid','unconfirmed')} | {'reasons':reasons}
        try:
            service.store.security_event(actor.login,'rule.batch','rule','failed' if result['error'] else 'invalid',context)
        except Exception:
            result['error'] = 'Confirmed rule results are retained, but batch audit summary could not be saved; check storage health.'
            result['status'] = 'interrupted'
    if not result['error']:
        result['status'] = 'partial' if result['added'] and (result['skipped'] or result['invalid']) else ('saved' if result['added'] else 'no_changes')
    if added and service.store.notifications:
        try:
            service.store.notifications.batch_committed(actor, result, added, comment)
        except Exception:
            # Delivery/enqueue errors never change already committed rule results.
            import logging
            logging.getLogger('uvicorn.error.notifications').error('Batch notification enqueue failed')
    return result
