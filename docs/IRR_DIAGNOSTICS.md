# Read-only IRR and protection diagnosis

The initial installation release v0.1.0 runs two separate processes per ASN:

```python
[config.irr_command, '-p', '-4', '-F', '%n/%l\n',
 '-h', config.irr_server, '-S', config.irr_sources, 'AS<number>']
[config.irr_command, '-p', '-6', '-F', '%n/%l\n',
 '-h', config.irr_server, '-S', config.irr_sources, 'AS<number>']
```

The format argument contains an actual newline, not a literal backslash+n.
Output must be ASCII canonical CIDR, one prefix per nonblank line, of the requested
family. JSON mode (-J -l NAME) is not the application's format. Blank output in
one family, including bgpq4 1.12's lone newline, is accepted when the other family
has data. Failure of either process rejects the whole refresh; it does not apply
a partial family result. An entirely empty result cannot initialize protection.
The timeout is config.timeout **per family** (default 15 seconds). Process output
is bounded: combined 32 MiB and stderr 64 KiB. ERROR:/FATAL: on stderr is treated
as failure even with exit status zero. Environment proxy variables are removed;
WHOIS needs TCP/43 or an independently configured transport.

## Persisted protection schedule

ProtectionWorker runs on both roles. It is polled every 60 seconds and stores a
per-ASN next-attempt timestamp in local protection_schedule. Failure sets next to
current time + 3600 seconds and retains the generic visible error and all cached
protection. Restart/reboot rereads that timestamp; it does not force an early
retry. Once due, a successful nonempty combined result grows the cache, clears
the schedule error and sets the next refresh to 30 days. These protection periods
are currently hardcoded, independent of the blocked-ASN irr_refresh_days option.
One ASN's success does not clear another ASN's error. Do not manually clear the
schedule or cache to hide an error.

## Probe compatible with the original installed resolver

The follow-up helper tools/diagnose_irr.py can be copied as standalone Python text
and run with the installed venv, including v0.1.0. It is not present in that old
tag, so do not assume that path already exists on an old checkout. Example after
placing the helper at a readable local path (choose actual operator targets):

```bash
sudo -u hemloc /opt/hemloc/.venv/bin/python -B /tmp/diagnose_irr.py \
  --config /etc/hemloc/hemloc.ini --asn 64496 --asn 64497
```

Alternatively feed the exact helper source on stdin with python -B - and the
same arguments. It calls the **installed IRR.expand and bounded_process**, recording
process status without replacing the parser/command/timeout logic. Its temporary
instrumentation runs only inside this separate diagnostic process, never inside
the serving application. Both ASNs are attempted even when one fails. It does
not construct Store, workers or GoBGP. Only the saved schedule is read through
SQLite mode=ro + query_only; no tables, cache or schedules are modified. It emits
no argv, raw stdout/stderr, exception text, prefixes, tokens or keys. Stderr hints
are fixed labels from at most the first 4096 captured bytes, not a complete
transcription. Unknown hints stay null; do not invent a cause from them.

The JSON distinguishes fresh resolver results from an old recorded schedule
error. If results are ok but retry_in_seconds is positive, the persisted warning
can be historical. This alone does not prove why the earlier refresh failed.
If an error is reproduced, use failing_family, exit_code, timeout/errno and the
fixed stderr hint. A shell success is not proof of a service-context success.

## systemd differs from sudo -u

The shipped service has NoNewPrivileges, PrivateTmp, ProtectSystem=strict,
ProtectHome, a write allowance only for /var/lib/hemloc, no capabilities and
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6. It sets WorkingDirectory=/opt/hemloc.
The shipped unit does not set PrivateNetwork or IPAddressDeny. Installed drop-ins
can differ; the probe displays selected actual effective properties, not secret
Environment values. It also shows the calling process's NoNewPrivs/Seccomp/CapEff.
A sudo -u command changes UID/groups but does not enter the running unit's mount,
private-tmp, seccomp or cgroup/network restrictions. PATH/executable location,
relative paths, file traversal, DNS access and drop-in filters can differ.
An executable under a home directory or a shell-relative path may therefore work
interactively and fail in the service. These are diagnostic possibilities, not
a finding about an unexamined host. Do not weaken hardening to guess a fix.

## Logging follow-up and verification

The original v0.1.0 worker discarded the exception and emitted no protection
failure journal message; a regression test reproduces the missing warning there.
The follow-up preserves family/exit/timeout/errno and bounded error categories.
Warnings include ASN, family (or combined), type, exit_code, timeout, errno and
an allowlisted stderr detail. Neither subprocess content nor exception tracebacks
are logged. Empty combined results are explicit failures. Success logs the ASN
and prefix count, clears old error diagnostics and keeps monotonic protection.
Logs use the configured uvicorn.error logger hierarchy, captured by systemd.

Tests use real subprocess timeouts/nonzero exits/error stderr, malformed responses,
a real bgpq4 with a loopback IRRD (including each empty family), persisted retry
and successful recovery with cache preservation. The read-only helper is also
tested with the original v0.1.0 modules. No production failure is deliberately
injected. No timer, routing or replication behavior is changed by this follow-up.

On an affected host: first save the read-only probe output. If failure reproduces,
resolve that specific failure rather than assuming an empty IPv6 set is wrong.
After a separately authorized deployment of the logging change, check journalctl
at/after the saved next-attempt time; look for the structured failure or success
and verify the UI error clears only after success. Only Hemloc needs an approved
restart to load new Python code; GoBGP does not. No deployment/restart is performed
by the probe or this documentation. If fresh shell results succeed but service
attempts still fail when due, collect effective unit differences and the new
structured journal entry before drawing a conclusion.
