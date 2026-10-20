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
    pass


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
                    raise IRRError("IRR timeout")
                ready = selector.select(remaining)
                if not ready:
                    raise IRRError("IRR timeout")
                for key, _ in ready:
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = data if key.fileobj is process.stdout else errors
                    target.extend(chunk)
                    if len(data) + len(errors) > max_bytes or len(errors) > 65536:
                        raise IRRError("IRR output limit exceeded")
            if process.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
                raise IRRError("IRR utility failed")
            if b'ERROR:' in errors.upper() or b'FATAL:' in errors.upper():
                raise IRRError('IRR utility reported an error')
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
        try:
            for version in (4, 6):
                args = [self.config.irr_command, '-p', f"-{version}", "-F", "%n/%l\n",
                        "-h", self.config.irr_server, "-S", self.config.irr_sources, f"AS{number}"]
                output = self.runner(args, self.config.timeout).decode("ascii", errors="strict")
                for line in output.splitlines():
                    if not line.strip():
                        continue
                    candidate = prefix(line)
                    if ipaddress.ip_network(candidate).version != version:
                        raise IRRError("Unexpected IRR address family")
                    result.add(candidate)
            return sorted(result)
        except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as exc:
            raise IRRError("IRR response unavailable or invalid") from exc


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
        with opener.open(Request(url, headers={"User-Agent": "Hemloc/0.1"}), timeout=self.config.timeout) as response:
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
