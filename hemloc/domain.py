"""Pure prefix and rule logic, independent of external services."""

from dataclasses import dataclass
import ipaddress


class Invalid(ValueError):
    pass


class Forbidden(PermissionError):
    pass


class Conflict(RuntimeError):
    pass


class Duplicate(Conflict):
    def __init__(self, rule_id):
        super().__init__("This rule already exists. Open the existing record.")
        self.rule_id = rule_id


class NeedSnapshot(Conflict):
    pass


class SplitBrain(Conflict):
    pass


def prefix(value: str) -> str:
    if not isinstance(value, str):
        raise Invalid("Prefix must be text")
    try:
        return str(ipaddress.ip_network(value.strip(), strict=True))
    except ValueError as exc:
        try:
            canonical = ipaddress.ip_network(value.strip(), strict=False)
        except ValueError:
            raise Invalid("Invalid IPv4/IPv6 address or CIDR") from exc
        raise Invalid(f"Host bits are set; use {canonical}") from exc


def asn(value) -> int:
    if isinstance(value, bool):
        raise Invalid("Invalid ASN")
    try:
        text = str(value).upper().removeprefix("AS")
        result = int(text)
    except (ValueError, TypeError) as exc:
        raise Invalid("Invalid ASN") from exc
    if not 1 <= result <= 4294967295 or str(result) != text:
        raise Invalid("ASN must be an integer in 1..4294967295")
    return result


@dataclass(frozen=True)
class Actor:
    login: str
    role: str

    def require_admin(self):
        if self.role != "admin":
            raise Forbidden("Administrator required")


class Protection:
    def __init__(self, prefixes=(), asns=()):
        self.prefixes = tuple(ipaddress.ip_network(prefix(p)) for p in prefixes)
        self.asns = frozenset(asn(a) for a in asns)

    def reason(self, candidate: str):
        net = ipaddress.ip_network(prefix(candidate))
        for protected in self.prefixes:
            if net.version == protected.version and net.subnet_of(protected):
                return f"{net} is inside protected {protected}"
        return None

    def check(self, candidate: str):
        reason = self.reason(candidate)
        if reason:
            raise Forbidden(reason)


def desired(rules, protection: Protection):
    routes, excluded = {}, []
    for rule in rules:
        for candidate in rule["prefixes"]:
            candidate = prefix(candidate)
            reason = protection.reason(candidate)
            if rule["kind"] == "asn" and rule["asn"] in protection.asns:
                reason = f"AS{rule['asn']} is protected locally"
            if reason:
                excluded.append({"prefix": candidate, "rule_id": rule["id"], "reason": reason})
            else:
                routes.setdefault(candidate, []).append(rule["id"])
    return routes, excluded


def lookup(address: str, rules):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise Invalid("Search requires an IPv4 or IPv6 address") from exc
    matches = []
    for rule in rules:
        prefixes = [p for p in rule["prefixes"]
                    if (n := ipaddress.ip_network(p)).version == ip.version and ip in n]
        if prefixes:
            matches.append({"rule": rule, "prefixes": prefixes})
    return matches
