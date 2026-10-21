"""Best-effort, bounded, single-attempt notification execution; no durable retry queue."""
from collections import OrderedDict, deque
from datetime import datetime
import ipaddress
import json
import logging
import os
import queue
import signal
import subprocess
import threading
import time
from zoneinfo import ZoneInfo

LOG = logging.getLogger('uvicorn.error.notifications')


def bounded(value, limit=500):
    return ''.join(c if c in '\n\t' or ord(c) >= 32 else ' ' for c in str(value))[:limit]


def field(value, limit=500):
    """Keep untrusted values on one labeled line inside a multiline message."""
    return bounded(value, limit).replace("\n", "\\n").replace("\t", "\\t")


class Notifications:
    def __init__(self, store, clock=time.time):
        self.store, self.config, self.clock = store, store.config, clock
        self.queue = queue.Queue(self.config.notification_queue_size)
        self.stop = threading.Event()
        self.threads = []
        self.sources = OrderedDict()
        self.lock = threading.Lock()

    def start(self):
        if self.config.notifications_enabled:
            for _ in range(self.config.notification_workers):
                thread = threading.Thread(target=self.worker, daemon=True, name='hemlock-notify')
                thread.start()
                self.threads.append(thread)

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(self.config.notification_timeout_seconds + 2)

    def failure(self, reason, exit_code=None):
        # Fixed reason codes only; no subprocess output, exception text or message body.
        LOG.warning('Notification failed reason=%s exit_code=%s', reason, exit_code)
        self.store.security_event('system:notifications', 'notification.failed', 'notification', 'failed', {'reason':reason, 'exit_code':exit_code})

    def submit(self, subject, body):
        if not self.config.notifications_enabled:
            return
        message = {'subject':bounded(subject, 200), 'body':bounded(body, 8000)}
        try:
            self.queue.put_nowait(message)
        except queue.Full:
            self.failure('queue_full')

    def worker(self):
        while not self.stop.is_set():
            try:
                message = self.queue.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                self.send(message)
            except Exception:
                LOG.error("Notification worker failed; message will not be retried")
            finally:
                self.queue.task_done()

    def send(self, message):
        try:
            process = subprocess.Popen([self.config.notification_script], stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True, close_fds=True)
            try:
                process.communicate(json.dumps(message, ensure_ascii=False).encode('utf-8'),
                                    timeout=self.config.notification_timeout_seconds)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                self.failure('timeout')
                return
            if process.returncode != 0:
                self.failure('exit_nonzero', process.returncode)
        except OSError:
            self.failure('executable_unavailable')

    def heading(self, kind):
        at = datetime.fromtimestamp(self.clock(), ZoneInfo(self.config.retention_timezone))
        return f'Node: {field(self.config.node_id, 100)}\nTime: {at.isoformat()} ({self.config.retention_timezone})\nEvent: {kind}'

    def committed(self, events):
        if not self.config.notifications_enabled or self.config.role != 'master' or not self.config.notification_blocklist_changes:
            return
        selected = []
        for event in events:
            if event['result'] != 'saved' or event['action'] not in ('rule.create', 'rule.import', 'rule.delete', 'rule.comment', 'asn.confirm', 'asn.refresh'):
                continue
            before, after = event.get('before') or {}, event.get('after') or {}
            if event['action'] in ('asn.refresh', 'asn.confirm') and before.get('prefixes') == after.get('prefixes'):
                continue
            selected.append(event)
        if not selected:
            return
        lines = [self.heading('Blocklist change'), f'Changes: {len(selected)}']
        for event in selected[:20]:
            before, after = event.get('before') or {}, event.get('after') or {}
            doc = after or before
            target = f"AS{doc.get('asn')}" if doc.get('kind') == 'asn' else ', '.join(doc.get('prefixes', [])[:2])
            added = len(set(after.get('prefixes', [])) - set(before.get('prefixes', [])))
            removed = len(set(before.get('prefixes', [])) - set(after.get('prefixes', [])))
            lines.append(f"Author: {field(event['actor'], 96)}; Action: {event['action']}; Target: {field(target, 150)}\nComment: {field(doc.get('comment', ''))}\nPrefixes: +{added} / -{removed}")
        if len(selected) > 20:
            lines.append(f'{len(selected)-20} further changes omitted')
        self.submit('Hemlock: blocklist changed', '\n'.join(lines))

    def batch_committed(self, actor, result, documents, comment):
        if self.config.role != 'master' or not self.config.notification_blocklist_changes:
            return
        body = (self.heading('Blocklist batch') + f"\nBatch: {result['batch_id']}\nAuthor: {field(actor.login,96)}"
                + f"\nAdded: {result['added']} · Skipped: {result['skipped']} · Invalid: {result['invalid']} · Unconfirmed: {result['unconfirmed']}"
                + f"\nComment: {field(comment)}\nPrefixes: " + ', '.join(d['prefixes'][0] for d in documents[:20]))
        self.submit('Hemlock: blocklist changed',body)

    def login_blocked(self, address, login, seconds):
        if not self.config.notification_login_blocked:
            return
        self.submit('Hemlock: login restricted', self.heading('Login rate limit') +
                    f'\nIP: {field(address, 50)}\nKnown login: {field(login or "Unknown", 96)}\nScope: application login attempts from this client IP\nRemaining restriction: {max(0, int(seconds))} seconds')

    def suspicious(self, address, kind):
        if not self.config.notifications_enabled or not self.config.notification_suspicious_access:
            return
        try:
            address = str(ipaddress.ip_address(address))
        except ValueError:
            return
        if kind not in ('invalid_request', 'unauthorized_request'):
            return
        now, cfg = self.clock(), self.config
        key = (address, kind)
        with self.lock:
            # Bounded source memory protects the application during distributed scans.
            state = self.sources.pop(key, {'events':deque(), 'notified':None})
            while state['events'] and state['events'][0] <= now - cfg.suspicious_window_seconds:
                state['events'].popleft()
            state['events'].append(now)
            while len(state['events']) > cfg.suspicious_threshold:
                state['events'].popleft()
            self.sources[key] = state
            if len(self.sources) > 10000:
                self.sources.popitem(last=False)
            if len(state['events']) < cfg.suspicious_threshold or (state['notified'] is not None and now - state['notified'] < cfg.suspicious_cooldown_seconds):
                return
            state['notified'] = now
        self.store.security_event('system:security', 'security.suspicious', 'request', 'denied',
                                  {'client_ip':address, 'window_seconds':cfg.suspicious_window_seconds,
                                   'count':len(state['events']), 'request_type':kind})
        self.submit('Hemlock: suspicious access', self.heading('Suspicious access') +
                    f'\nIP: {address}\nWindow: {cfg.suspicious_window_seconds} seconds\nCount: at least {len(state["events"])}\nRequest type: {kind}')
