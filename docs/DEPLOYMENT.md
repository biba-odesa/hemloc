# Debian 13 deployment

These commands are an operator checklist, not permission to install or start
services. Do not change host networking, firewall or SSH. Review an existing
installation before updating it; never overwrite its configuration or database.
All addresses and ASNs below and in deploy/ are documentation values.

## Checkout and dependencies

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends git python3.13-venv ca-certificates bgpq4
git clone --branch v0.1.0 --single-branch https://github.com/biba-odesa/hemloc.git
cd hemloc
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
sudo chown root:hemloc /etc/hemloc/hemloc.ini
sudo chmod 0640 /etc/hemloc/hemloc.ini
sudo stat -c '%U:%G %a %n' /etc/hemloc/hemloc.ini
sudo -u hemloc test -r /etc/hemloc/hemloc.ini
```

Editors can replace the INI and change its owner/mode. Repeat these checks after
every edit; expect root:hemloc 640 and successful service-user reading.

Select unique node_id and owner namespace, database path, role, peer identity,
HTTPS binding/certificate/key/trusted CA and a private replication-token file.
Use a separately generated token with at least 32 non-whitespace characters.
Replace documentation ASNs, next-hops, communities, protection and proxy settings.
Never infer IPv6 next-hop. Keep announcements=no and GoBGP peer-free at bootstrap.
HTTP is available only as an explicitly selected local setup mode; use HTTPS for
network access and replication. [OPERATIONS.md](OPERATIONS.md) covers TLS and SAN.

## Initialize master or slave

Maintenance CLI, including init-db, requires root. Initialize before starting the
service, then transfer database/sidecar/lock ownership to the service account.
Set role=master or role=slave explicitly in the local INI first:

```bash
sudo /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini init-db
sudo chown -R hemloc:hemloc /var/lib/hemloc
sudo chmod 0700 /var/lib/hemloc
```

**Master only:** create the first administrator interactively:

```bash
sudo /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini user create operator --role admin
```

**Slave:** do not create users or reset passwords. Prepare authenticated verified
HTTPS to the master and transfer the retained local protection separately; users,
rules, ASN sets and shared audit arrive through snapshot/journal. Follow the
self-contained Russian [slave installation guide](INSTALL_B.md), including the
explicit v0.1.0 protection-transfer gap and bootstrap procedure.

**Both roles:** install the units after reviewing their paths and permissions:

```bash
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

## Source access and operator-selected announcement mode

HTTP_PROXY/HTTPS_PROXY do not provide WHOIS transport for bgpq4. IRR requires
TCP/43 or a separately designed transport. Slaves receive blocked ASN sets from
the master, but refresh local protection independently and retain its cache on
IRR failure. After promotion, IRR is also needed for blocked ASN updates.
A changed protected-ASN configuration must be reread by Hemloc and every new
ASN successfully initialized before taking a fresh protection export.

After bootstrap, an operator may choose announcements=yes on the slave while
retaining per-neighbor import/export DENY-ANY on the routers. This permits local
RIB/export validation without claiming router installation. Do not automatically
reset that chosen mode; actual policy acceptance remains a separate decision.
See INSTALL_B.md for the copyable procedure. No service action is implied by
this documentation update.
