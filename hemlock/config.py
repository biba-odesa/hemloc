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
    database: str = "/var/lib/hemlock/hemlock.sqlite"
    host: str = "127.0.0.1"
    port: int = 8443
    tls: bool = True
    cert: str = ""
    key: str = ""
    ca: str = ""
    tls_mode: str = "legacy_ca"
    tls_state_dir: str = ""
    tls_names: tuple = ()
    tls_days: int = 365
    tls_warn_days: int = 30
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

    batch_max_items: int = 1000
    request_max_bytes: int = 2097152
    retention_enabled: bool = False
    blocklist_days: int = 365
    users_access_days: int = 90
    errors_security_days: int = 7
    cleanup_time: str = "01:00"
    retention_timezone: str = "Europe/Kyiv"
    retention_batch_size: int = 200
    notifications_enabled: bool = False
    gobgp_service_unit: str = "gobgp.service"
    notification_script: str = "/usr/sbin/notify_script"
    notification_timeout_seconds: float = 15.0
    notification_blocklist_changes: bool = True
    notification_login_blocked: bool = True
    notification_suspicious_access: bool = True
    notification_queue_size: int = 100
    notification_workers: int = 1
    suspicious_threshold: int = 30
    suspicious_window_seconds: int = 60
    suspicious_cooldown_seconds: int = 900

    def validate(self):
        import re
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*\.service', self.gobgp_service_unit):
            raise Invalid('Invalid GoBGP read-only status unit name')
        if not 1 <= self.batch_max_items <= 10000 or not 16384 <= self.request_max_bytes <= 16777216:
            raise Invalid("batch_max_items must be 1..10000; request_max_bytes 16384..16777216")
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        import datetime
        try:
            ZoneInfo(self.retention_timezone)
            datetime.time.fromisoformat(self.cleanup_time)
        except (ValueError, ZoneInfoNotFoundError):
            raise Invalid("Invalid retention timezone or cleanup_time") from None
        if (len(self.cleanup_time) != 5 or any(not 1 <= v <= 36500 for v in (self.blocklist_days, self.users_access_days, self.errors_security_days))
                or not 1 <= self.retention_batch_size <= 500):
            raise Invalid("Retention days must be 1..36500; batch size 1..500")
        if (not Path(self.notification_script).is_absolute() or "\x00" in self.notification_script or not 0 < self.notification_timeout_seconds <= 120
                or not 1 <= self.notification_queue_size <= 10000 or not 1 <= self.notification_workers <= 4
                or not 1 <= self.suspicious_threshold <= 100000 or not 1 <= self.suspicious_window_seconds <= 3600
                or not 1 <= self.suspicious_cooldown_seconds <= 86400):
            raise Invalid("Invalid notification settings")
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
        if self.tls_mode not in ('legacy_ca','pinned'):
            raise Invalid('TLS mode must be legacy_ca or pinned')
        if self.tls_mode=='pinned':
            if not all(re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',v) for v in (self.node_id,self.peer_node_id)):raise Invalid('Pinned TLS requires a bounded node ID')
            if self.peer_url and urlsplit(self.peer_url).path not in ('','/'):raise Invalid('Pinned peer_url must not contain a path prefix')
            if not self.tls or not self.tls_state_dir or not Path(self.tls_state_dir).is_absolute():
                raise Invalid('Pinned TLS requires HTTPS and an absolute tls state_dir')
            if not 1<=self.tls_days<=825 or not 1<=self.tls_warn_days<=90:
                raise Invalid('TLS days must be 1..825; warn_days 1..90')
            if not self.cert or not self.key or Path(self.cert).parent!=Path(self.key).parent or self.cert==self.key:
                raise Invalid('Pinned certificate/key require a dedicated shared identity directory')
            if Path(self.cert).parent.parent!=Path(self.tls_state_dir):
                raise Invalid('Certificate/key need a dedicated identity directory directly under tls state_dir')
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
        "tls": ("tls_mode", "tls_state_dir", "tls_names", "tls_days", "tls_warn_days"),
        "retention": ("retention_enabled", "blocklist_days", "users_access_days", "errors_security_days", "cleanup_time", "retention_timezone", "retention_batch_size"),
        "notifications": ("notifications_enabled", "notification_script", "notification_timeout_seconds", "notification_blocklist_changes", "notification_login_blocked", "notification_suspicious_access", "notification_queue_size", "notification_workers", "suspicious_threshold", "suspicious_window_seconds", "suspicious_cooldown_seconds"),
        "node": ("node_id", "role", "database", "peer_url", "peer_node_id", "token_file", "poll_seconds"),
        "web": ("host", "port", "tls", "cert", "key", "ca", "batch_max_items", "request_max_bytes"),
        "proxy": ("use_proxy", "http_proxy", "https_proxy", "no_proxy"),
        "protection": ("protected_asns", "protected_prefixes"),
        "irr": ("irr_command", "irr_server", "irr_sources", "irr_refresh_days", "timeout", "change_ratio", "change_absolute", "max_prefixes"),
        "metadata": ("metadata_enabled",),
        "gobgp": ("announcements", "grpc_target", "gobgp_service_unit", "v4_next_hop", "v6_next_hop", "local_pref", "community", "owner"),
    }
    defaults, values = Config(), {}
    for section, fields in mapping.items():
        if not ini.has_section(section):
            continue
        for name in fields:
            key = name.removeprefix("tls_") if section=="tls" else {"http_proxy": "http", "https_proxy": "https", "retention_enabled": "enabled", "retention_timezone": "timezone", "retention_batch_size": "batch_size", "notifications_enabled": "enabled"}.get(name, name)
            if section == "notifications" and name.startswith("notification_"):
                key = name.removeprefix("notification_")
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
    for name in ("database", "token_file", "cert", "key", "ca", "tls_state_dir"):
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
