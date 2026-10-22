"""Explicit, isolated empty-daemon startup demotion for shared fixtures."""
from hemlock.store import Store
from hemlock.transition import RoleTransition


class EmptyDedicatedDaemon:
    def drain_for_transition(self):pass
    def confirmed_absent(self):return False


def demote(config):
    RoleTransition(config).prepare(EmptyDedicatedDaemon())
    return Store(config)
