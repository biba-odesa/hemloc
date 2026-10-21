"""Bounded direct WHOIS expansion and explicitly proxied metadata HTTP."""

import ipaddress
import json
import os
import selectors
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import ProxyHandler, HTTPSHandler, build_opener, Request
import ssl

from .config import proxy_for
from .domain import Invalid, asn, prefix


class IRRError(RuntimeError):
    def __init__(self, message, *, category='resolver', exit_code=None, timed_out=False,
                 family=None, number=None, os_errno=None, detail=None):
        super().__init__(message)
        self.category = category
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.family = family
        self.number = number
        self.os_errno = os_errno
        self.detail = detail


def stderr_category(data):
    """Return a fixed label, never subprocess text or credentials."""
    lowered = data.lower()
    for pattern, label in (
        (b'permission denied', 'permission_denied'),
        (b'operation not permitted', 'operation_not_permitted'),
        (b'connection refused', 'connection_refused'),
        (b'connection timed out', 'connection_timeout'),
        (b'network is unreachable', 'network_unreachable'),
        (b'no route to host', 'no_route'),
        (b'name or service not known', 'dns_failure'),
        (b'temporary failure in name resolution', 'dns_failure'),
        (b'invalid option', 'invalid_option'),
        (b'unrecognized option', 'invalid_option'),
    ):
        if pattern in lowered:
            return label
    return None


def failure_details(error):
    """Bounded, allowlisted diagnostic fields suitable for journals and JSON."""
    categories = {'resolver', 'timeout', 'output_limit', 'exit', 'utility_error',
                  'os_error', 'invalid_output', 'family_mismatch', 'empty', 'internal'}
    result = {'category': 'internal', 'family': None, 'exit_code': None,
              'timed_out': False, 'os_errno': None, 'detail': None}
    if isinstance(error, IRRError):
        result.update(category=error.category if error.category in categories else 'resolver',
                      family=error.family if error.family in (4, 6) else None,
                      exit_code=error.exit_code if type(error.exit_code) is int else None,
                      timed_out=error.timed_out is True,
                      os_errno=error.os_errno if type(error.os_errno) is int else None)
        if error.detail in {'permission_denied', 'operation_not_permitted', 'connection_refused',
                            'connection_timeout', 'network_unreachable', 'no_route',
                            'dns_failure', 'invalid_option'}:
            result['detail'] = error.detail
    elif isinstance(error, OSError):
        result.update(category='os_error', os_errno=error.errno)
    return result


def bounded_process(args, timeout, max_bytes=32 * 1024 * 1024):
    """Bound stdout in memory and time; stderr is never surfaced or logged."""
    env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as process:
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        selector.register(process.stderr, selectors.EVENT_READ)
        deadline, data, errors = time.monotonic() + timeout, bytearray(), bytearray()
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise IRRError("IRR timeout", category='timeout', timed_out=True)
                ready = selector.select(remaining)
                if not ready:
                    raise IRRError("IRR timeout", category='timeout', timed_out=True)
                for key, _ in ready:
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = data if key.fileobj is process.stdout else errors
                    target.extend(chunk)
                    if len(data) + len(errors) > max_bytes or len(errors) > 65536:
                        raise IRRError("IRR output limit exceeded", category='output_limit')
            try:
                code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise IRRError('IRR timeout', category='timeout', timed_out=True) from exc
            if code != 0:
                raise IRRError("IRR utility failed", category='exit', exit_code=code,
                               detail=stderr_category(errors))
            if b'ERROR:' in errors.upper() or b'FATAL:' in errors.upper():
                raise IRRError('IRR utility reported an error', category='utility_error',
                               exit_code=code, detail=stderr_category(errors))
            return bytes(data)
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            selector.close()


class IRR:
    def __init__(self, config, runner=bounded_process):
        self.config, self.runner = config, runner

    def expand(self, number):
        number = asn(number)
        result = set()
        for version in (4, 6):
            try:
                args = [self.config.irr_command, '-p', f"-{version}", "-F", "%n/%l\n",
                        "-h", self.config.irr_server, "-S", self.config.irr_sources, f"AS{number}"]
                output = self.runner(args, self.config.timeout).decode("ascii", errors="strict")
                for line in output.splitlines():
                    if not line.strip():
                        continue
                    candidate = prefix(line)
                    if ipaddress.ip_network(candidate).version != version:
                        raise IRRError("Unexpected IRR address family", category='family_mismatch')
                    result.add(candidate)
            except IRRError as exc:
                exc.family, exc.number = version, number
                raise
            except subprocess.TimeoutExpired as exc:
                raise IRRError('IRR timeout', category='timeout', timed_out=True,
                               family=version, number=number) from exc
            except OSError as exc:
                raise IRRError('IRR process unavailable', category='os_error', os_errno=exc.errno,
                               family=version, number=number) from exc
            except (ValueError, subprocess.SubprocessError) as exc:
                raise IRRError("IRR response unavailable or invalid", category='invalid_output',
                               family=version, number=number) from exc
        return sorted(result)


class Metadata:
    """RIPEstat read-only metadata; never infer network ownership from its first IP."""
    def __init__(self, config, opener_factory=build_opener):
        self.config, self.opener_factory = config, opener_factory
        self.cache = {}

    def _get(self, endpoint, resource):
        if not self.config.metadata_enabled:
            raise Invalid("External metadata is disabled locally")
        key = endpoint, resource
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        url = f"https://stat.ripe.net/data/{endpoint}/data.json?" + urlencode({"resource": resource})
        proxy = proxy_for(self.config, url)
        opener = self.opener_factory(ProxyHandler({"https": proxy} if proxy else {}),
                                     HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(Request(url, headers={"User-Agent": "Hemlock/0.1"}), timeout=self.config.timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise Invalid("Metadata response too large")
            body = json.loads(raw)
            if body.get("status") != "ok" or not isinstance(body.get("data"), dict):
                raise Invalid("Invalid metadata response")
            data = body["data"]
        if len(self.cache) >= 1024:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = time.monotonic() + 3600, data
        return data

    def asn_name(self, number):
        return str(self._get("as-overview", f"AS{asn(number)}").get("holder") or "")[:1000]

    def origins(self, candidate):
        network = ipaddress.ip_network(prefix(candidate))
        if network.prefixlen != network.max_prefixlen:
            return []
        data = self._get("network-info", str(network.network_address))
        announced = ipaddress.ip_network(data["prefix"])
        if announced.version != network.version or not network.subnet_of(announced):
            raise Invalid("Metadata prefix mismatch")
        origins = []
        for number in data.get("asns", []):
            number = asn(number)
            try:
                name = self.asn_name(number)
            except Exception:
                name = ""
            origins.append({"asn": number, "name": name, "source": "RIPEstat network-info / as-overview", "at": time.time()})
        return origins
