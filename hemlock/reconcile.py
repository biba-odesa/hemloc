"""Actual-RIB reconciliation with explicit ownership and final protection checks."""

from dataclasses import dataclass, field
import ipaddress
import time

from .domain import Conflict


@dataclass(frozen=True)
class Path:
    uuid: str
    prefix: str
    next_hop: str
    local_pref: int
    communities: tuple
    owner: tuple
    local: bool = True
    identifier: int = 0
    wire: bytes = field(default=b'', repr=False, compare=False)

    @property
    def key(self):
        return self.prefix, self.identifier


class Reconciler:
    def __init__(self, service, adapter):
        self.service, self.adapter = service, adapter

    def attributes(self, candidate):
        config = self.service.config
        version = ipaddress.ip_network(candidate).version
        hop = config.v4_next_hop if version == 4 else config.v6_next_hop
        if not hop:
            return None
        preference = config.local_pref if version == 4 else config.v6_local_pref
        community = config.community if version == 4 else config.v6_community
        return hop, preference, (community,), config.owner

    def owned(self, path):
        return path.local and path.owner == self.service.config.owner

    def matches(self, path, attrs):
        return (path.next_hop, path.local_pref, path.communities, path.owner) == attrs

    def step(self):
        config = self.service.config
        from .transition import RoleTransition
        RoleTransition(config).guard(self.adapter)
        routes, exclusions, info = self.service.route_snapshot()
        status = {"at": time.time(), "enabled": config.announcements, "desired": len(routes),
                  "confirmed": [], "excluded": len(exclusions), "error": "", "router_acceptance": "unknown"}
        status.update({'history': info['history'], 'sequence': info['sequence']})
        if not config.announcements:
            status["mode"] = "disabled: no route writes; existing paths retained; reconciliation not performed"
            status["reconciliation_performed"] = False
            self.service.store.set_local("bgp", status)
            return status
        actual = self.adapter.paths()
        owned_by_prefix = {}
        protection = self.service.protection()
        for path in actual:
            if self.owned(path):
                owned_by_prefix.setdefault(path.prefix, []).append(path)
        # Withdraw forbidden/stale owned paths even if protection initialization is incomplete.
        for path in actual:
            if self.owned(path) and (path.prefix not in routes or self.attributes(path.prefix) is None or protection.reason(path.prefix)):
                self.adapter.delete(path)
        if not self.service.protection_ready():
            raise Conflict("Protected ASN bootstrap incomplete; additions are blocked")
        for candidate in routes:
            protection.check(candidate)
            attrs = self.attributes(candidate)
            if attrs is None:
                continue
            matching = owned_by_prefix.get(candidate, [])
            if any(self.matches(p, attrs) for p in matching):
                kept = False
                for path in matching:
                    if self.matches(path, attrs) and not kept:
                        kept = True
                    else:
                        self.adapter.delete(path)
                continue
            for path in matching:
                self.adapter.delete(path)
            # Recheck protection immediately before submitting the path.
            self.service.protection().check(candidate)
            self.adapter.add(candidate, attrs)
        observed = self.adapter.paths()
        status["confirmed"] = sorted({p.prefix for p in observed if self.owned(p) and
                                      p.prefix in routes and self.matches(p, self.attributes(p.prefix))})
        status["missing_next_hop"] = sorted(p for p in routes if self.attributes(p) is None)
        status["mode"] = "observed in local GoBGP only"
        status["reconciliation_performed"] = True
        self.service.store.set_local("bgp", status)
        return status
