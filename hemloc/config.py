"""Local configuration and explicit proxy policy."""

from configparser import ConfigParser
from dataclasses import dataclass
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from .domain import Invalid, Protection


@dataclass(frozen=True)
class Config:
    node_id: str = "block-a"
    role: str = "master"
    database: str = "var/hemloc.sqlite"
    host: str = "127.0.0.1"
    port: int = 8443
    tls: bool = True
    cert: str = ""
    key: str = ""
    ca: str = ""
    peer_url: str = ""
    peer_node_id: str = "block-b"
    token_file: str = ""
    poll_seconds: float = 3.0
    timeout: float = 15.0
    use_proxy: bool = False
    http_proxy: str = ""
    https_proxy: str = ""
    no_proxy: tuple = ("localhost", "127.0.0.1", "::1", "block-a", "block-b")
    protected_asns: tuple = (64496,)
    protected_prefixes: tuple = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    irr_command: str = "bgpq4"
    irr_server: str = "whois.radb.net"
    irr_sources: str = "RIPE,RADB"
    irr_refresh_days: int = 30
    change_ratio: float = 0.5
    change_absolute: int = 10000
    max_prefixes: int = 100000
    metadata_enabled: bool = True
    announcements: bool = False
    grpc_target: str = "127.0.0.1:50051"
    v4_next_hop: str = "192.0.2.254"
    v6_next_hop: str = ""
    local_pref: int = 200
    community: str = "64512:666"
    v6_local_pref: int = 200
    v6_community: str = "64512:666"
    owner: tuple = (64512, 100, 1)

    def validate(self):
        if self.role not in ("master", "slave"):
            raise Invalid("role must be master or slave")
        if not self.node_id or self.peer_node_id == self.node_id:
            raise Invalid("Unique local and peer node IDs required")
        if self.poll_seconds < 0.1 or self.timeout <= 0:
            raise Invalid("Invalid polling interval or timeout")
        if not 0 < self.change_ratio <= 1 or self.change_absolute < 1 or self.max_prefixes < 1:
            raise Invalid("Invalid IRR change thresholds")
        if self.irr_refresh_days < 1 or not 1 <= self.port <= 65535:
            raise Invalid("Invalid refresh interval or web port")
        if self.peer_url:
            url = urlsplit(self.peer_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise Invalid("Replication requires a credential-free HTTPS URL")
        if self.tls and (not self.cert or not self.key):
            raise Invalid("HTTPS requires certificate and key; choose HTTP explicitly for bootstrap")
        if self.grpc_target.rsplit(":", 1)[0] not in ("127.0.0.1", "localhost", "[::1]"):
            raise Invalid("GoBGP gRPC must be loopback")
        if len(self.owner) != 3 or any(type(v) is not int or not 0 <= v <= 4294967295 for v in self.owner):
            raise Invalid("Ownership marker requires three uint32 values")
        for value in (self.local_pref, self.v6_local_pref):
            if not 0 <= value <= 4294967295:
                raise Invalid("Local preference must be uint32")
        for value in (self.community, self.v6_community):
            parts = value.split(':')
            if len(parts) != 2 or any(not p.isdigit() or not 0 <= int(p) <= 65535 for p in parts):
                raise Invalid("Invalid standard community")
        for value, version in ((self.v4_next_hop, 4), (self.v6_next_hop, 6)):
            if value and ipaddress.ip_address(value).version != version:
                raise Invalid("Wrong next-hop address family")
        Protection(self.protected_prefixes, self.protected_asns)
        return self


def load(path: str) -> Config:
    ini = ConfigParser(interpolation=None)
    if not ini.read(path):
        raise Invalid(f"Cannot read config: {path}")
    mapping = {
        "node": ("node_id", "role", "database", "peer_url", "peer_node_id", "token_file", "poll_seconds"),
        "web": ("host", "port", "tls", "cert", "key", "ca"),
        "proxy": ("use_proxy", "http_proxy", "https_proxy", "no_proxy"),
        "protection": ("protected_asns", "protected_prefixes"),
        "irr": ("irr_command", "irr_server", "irr_sources", "irr_refresh_days", "timeout", "change_ratio", "change_absolute", "max_prefixes"),
        "metadata": ("metadata_enabled",),
        "gobgp": ("announcements", "grpc_target", "v4_next_hop", "v6_next_hop", "local_pref", "community", "owner"),
    }
    defaults, values = Config(), {}
    for section, fields in mapping.items():
        if not ini.has_section(section):
            continue
        for name in fields:
            key = {"http_proxy": "http", "https_proxy": "https"}.get(name, name)
            if not ini.has_option(section, key):
                continue
            default = getattr(defaults, name)
            raw = ini.get(section, key).strip()
            if isinstance(default, bool):
                values[name] = ini.getboolean(section, key)
            elif isinstance(default, int):
                values[name] = int(raw)
            elif isinstance(default, float):
                values[name] = float(raw)
            elif isinstance(default, tuple):
                items = tuple(v.strip() for v in raw.split(",") if v.strip())
                values[name] = tuple(int(v) for v in items) if name in ("owner", "protected_asns") else items
            else:
                values[name] = raw
    for name in ("database", "token_file", "cert", "key", "ca"):
        if values.get(name) and not Path(values[name]).is_absolute():
            values[name] = str((Path(path).resolve().parent / values[name]).resolve())
    for section, targets in {
        "gobgp_ipv4": {"next_hop": "v4_next_hop", "local_preference": "local_pref", "community": "community"},
        "gobgp_ipv6": {"next_hop": "v6_next_hop", "local_preference": "v6_local_pref", "community": "v6_community"},
    }.items():
        for key, target in targets.items():
            if ini.has_option(section, key):
                values[target] = ini.getint(section, key) if key == "local_preference" else ini.get(section, key).strip()
    return Config(**values).validate()


def proxy_for(config: Config, url: str):
    """Never consult environment variables; no_proxy uses hostname boundaries."""
    if not config.use_proxy:
        return None
    host = (urlsplit(url).hostname or "").lower()
    for entry in config.no_proxy:
        entry = entry.lower().lstrip(".")
        if entry == "*" or host == entry or host.endswith("." + entry):
            return None
        try:
            if ipaddress.ip_address(host) in ipaddress.ip_network(entry):
                return None
        except ValueError:
            pass
    return config.https_proxy if urlsplit(url).scheme == "https" else config.http_proxy
