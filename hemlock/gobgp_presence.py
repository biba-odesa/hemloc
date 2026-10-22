"""Conservative, read-only evidence of an absent dedicated local daemon."""
from pathlib import Path
import socket
import subprocess


def confirmed_absent(config, *, proc=Path('/proc'), run=subprocess.run, connect=socket.create_connection):
    # A refused endpoint alone does not prove the daemon is stopped. Read only
    # the configured systemd unit's state; never request a state change or sudo.
    try:
        result = run(['/usr/bin/systemctl','show',config.gobgp_service_unit,'--no-pager',
                      '--property=LoadState,ActiveState,SubState,MainPID,ControlPID'],
                     stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                     timeout=2,check=False)
        status = dict(line.split('=',1) for line in result.stdout.decode().splitlines() if '=' in line)
        if result.returncode or status != {'LoadState':'loaded','ActiveState':'inactive','SubState':'dead','MainPID':'0','ControlPID':'0'}:
            return False
        # Refuse an absence claim if /proc visibility is restricted or another
        # independently started canonical daemon is visible.
        mounts=(proc/'self/mountinfo').read_text()
        proc_mounts=[line for line in mounts.splitlines() if len(line.split())>5 and line.split()[4]=='/proc']
        if not proc_mounts or any('hidepid=' in line and 'hidepid=0' not in line for line in proc_mounts):return False
        if (proc/'1/comm').read_text().strip() not in ('systemd','init'):return False
        for item in proc.iterdir():
            if not item.name.isdigit():continue
            try:
                if (item/'comm').read_text().strip()=='gobgpd':return False
            except FileNotFoundError:continue
        host,port=config.grpc_target.rsplit(':',1)
        host=host.strip('[]')
        addresses=socket.getaddrinfo(host,int(port),type=socket.SOCK_STREAM)
        if not addresses:return False
        for family,kind,protocol,canonical,address in addresses:
            try:
                connection=connect(address[:2],timeout=1)
            except ConnectionRefusedError:continue
            else:
                connection.close();return False
        return True
    except (OSError,ValueError,UnicodeError,subprocess.SubprocessError):
        return False
