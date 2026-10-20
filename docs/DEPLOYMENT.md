# Debian 13 deployment

These commands are an operator checklist, not permission to install or start
services. Do not change host networking, firewall or SSH. Review an existing
installation before updating it; never overwrite its configuration or database.
All addresses and ASNs below and in deploy/ are documentation values.

## Checkout and dependencies

```bash
git clone --branch v0.1.0 --single-branch https://github.com/biba-odesa/hemloc.git
cd hemloc
sudo apt-get update
sudo apt-get install --no-install-recommends git python3.13-venv ca-certificates bgpq4
```

Install a separately verified GoBGP binary using [BUILD.md](BUILD.md). Hemloc
requires the 4.10.0 API. The explicit internal-peer TTL patch is separate from
application packaging; do not substitute a different major API.

```bash
sudo useradd --system --user-group --home-dir /var/lib/hemloc --shell /usr/sbin/nologin hemloc
sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin gobgp
sudo install -d -o root -g hemloc -m 0750 /etc/hemloc
sudo install -d -o root -g gobgp -m 0750 /etc/gobgp
sudo install -d -o hemloc -g hemloc -m 0700 /var/lib/hemloc
sudo git clone --branch v0.1.0 --single-branch https://github.com/biba-odesa/hemloc.git /opt/hemloc
sudo python3 -m venv /opt/hemloc/.venv
sudo /opt/hemloc/.venv/bin/python -m pip install --require-hashes -r /opt/hemloc/requirements.lock
sudo /opt/hemloc/.venv/bin/python -m pip install --require-hashes -r /opt/hemloc/requirements-build.lock
sudo /opt/hemloc/.venv/bin/python -m pip install --no-build-isolation --no-deps /opt/hemloc
sudo /opt/hemloc/.venv/bin/python -m pip check
sudo install -o root -g hemloc -m 0640 deploy/hemloc.example.ini /etc/hemloc/hemloc.ini
sudo install -o root -g gobgp -m 0640 deploy/gobgpd.example.toml /etc/gobgp/gobgpd.toml
sudoedit /etc/hemloc/hemloc.ini
```

Select unique node_id and owner namespace, database path, role, peer identity,
HTTPS binding/certificate/key/trusted CA and a private replication-token file.
Use a separately generated token with at least 32 non-whitespace characters.
Replace documentation ASNs, next-hops, communities, protection and proxy settings.
Never infer IPv6 next-hop. Keep announcements=no and GoBGP peer-free at bootstrap.
HTTP is available only as an explicitly selected local setup mode; use HTTPS for
network access and replication. [OPERATIONS.md](OPERATIONS.md) covers TLS and SAN.

Initialize as the service account; create the first administrator only on master:

```bash
sudo -u hemloc /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini init-db
sudo /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini user create operator --role admin
sudo install -o root -g root -m 0644 deploy/hemloc.service /etc/systemd/system/hemloc.service
sudo install -o root -g root -m 0644 deploy/gobgp.service /etc/systemd/system/gobgp.service
sudo systemd-analyze verify /etc/systemd/system/hemloc.service /etc/systemd/system/gobgp.service
sudo systemctl daemon-reload
```

After separate authorization start the services, verify HTTPS, local-only gRPC,
protection initialization and disabled announcements. Configure BGP peers and
export policies separately; never copy documentation peers into a working setup.
Then enable autostart if appropriate. Never use multiple Uvicorn workers.

The GoBGP unit runs unprivileged without CAP_NET_BIND_SERVICE. The shipped test
configuration uses loopback BGP port 1179 and gRPC 50051; outbound-only managed
setups can disable the BGP listener. The gRPC bind address is set by the unit's
command line, not by Hemloc. Do not expose it on a nonlocal address.
