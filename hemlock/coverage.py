"""Cached prefix-length and address-range indexes for read-only rule coverage."""
from bisect import bisect_left, bisect_right
import ipaddress
import threading
from .store import digest

_lock = threading.Lock()


class CoverageIndex:
    def __init__(self, view):
        self.rules = view.rules
        self.levels = {4: {}, 6: {}}
        self.entries = {4: [], 6: []}
        for candidate, ids in view.routes.items():
            net = ipaddress.ip_network(candidate)
            start = int(net.network_address)
            self.levels[net.version].setdefault(net.prefixlen, {}).setdefault(start, set()).update(ids)
            self.entries[net.version].append((start, net.prefixlen, tuple(ids)))
        for version in (4, 6):
            self.entries[version].sort()
        self.starts = {v: [e[0] for e in self.entries[v]] for v in (4, 6)}

    def related(self, value, own=''):
        net = ipaddress.ip_network(value)
        start, end = int(net.network_address), int(net.broadcast_address)
        result = {'asn': set(), 'manual': set(), 'contains': set()}
        for length, level in self.levels[net.version].items():
            if length > net.prefixlen:
                continue
            address = (start >> (net.max_prefixlen-length)) << (net.max_prefixlen-length)
            for key in level.get(address, ()):
                if key != own:
                    result[self.rules[key]['kind']].add(key)
        entries = self.entries[net.version]
        for position in range(bisect_left(self.starts[net.version], start), bisect_right(self.starts[net.version], end)):
            _, length, keys = entries[position]
            if length > net.prefixlen:
                result['contains'].update(key for key in keys if key != own)
        return result

    def summary(self, value, own=''):
        net = ipaddress.ip_network(value)
        if own and own not in self.levels[net.version].get(net.prefixlen, {}).get(int(net.network_address), set()):
            return []
        groups = self.related(value, own)
        badges = []
        for relation in ('asn', 'manual'):
            ids = sorted(groups[relation])
            if ids:
                labels = [('AS'+str(self.rules[key]['asn'])) if relation=='asn' else self.rules[key]['prefixes'][0] for key in ids]
                label = 'Covered by '+', '.join(labels[:3])+(f' + {len(ids)-3} more' if len(ids)>3 else '')
                badges.append({'relation': relation, 'label': label, 'count': len(ids)})
        count = len(groups['contains'])
        if count:
            badges.append({'relation': 'contains', 'label': f'Contains {count} block'+('s' if count!=1 else ''), 'count': count})
        return badges


def index_for(view):
    """One revision per service: journal, snapshot history and local protection invalidate."""
    key = (view.info['history'], view.info['sequence'],
           digest([sorted(str(p) for p in view.protection.prefixes), sorted(view.protection.asns)]))
    with _lock:
        cached = getattr(view.service, '_coverage_index', None)
        if cached is None or cached[0] != key:
            cached = (key, CoverageIndex(view))
            view.service._coverage_index = cached
        return cached[1]
