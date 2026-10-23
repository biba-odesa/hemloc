"""Create a private loopback-only two-node lab; never start services."""

import argparse
from configparser import ConfigParser
import os
from pathlib import Path
import secrets
import subprocess
import sys


def openssl(*args):
    subprocess.run(['openssl', *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default='var/lab')
    parser.add_argument('--port-a', type=int, default=18443)
    parser.add_argument('--port-b', type=int, default=18444)
    args = parser.parse_args()
    if args.port_a == args.port_b or any(not 1024 <= p <= 65535 for p in (args.port_a, args.port_b)):
        parser.error('Use distinct unprivileged ports')
    os.umask(0o077)
    directory = Path(args.directory).resolve()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072', '-out', str(directory/'ca.key'))
    openssl('req', '-x509', '-new', '-key', str(directory/'ca.key'), '-sha256', '-days', '30',
            '-subj', '/CN=Hemlock-Test-CA', '-out', str(directory/'ca.crt'),
            '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    (directory/'peer.token').write_text(secrets.token_urlsafe(48) + '\n')
    fixture = Path(__file__).resolve().with_name('lab_irr.py')
    for label, port, peer, peer_port, role in [('a',args.port_a,'b',args.port_b,'master'), ('b',args.port_b,'a',args.port_a,'slave')]:
        key, csr, cert = (str(directory/f'{label}.{ext}') for ext in ('key','csr','crt'))
        extension = directory/f'{label}.ext'
        extension.write_text(f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:block-{label},DNS:localhost,IP:127.0.0.1\n')
        openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072', '-out', key)
        openssl('req', '-new', '-key', key, '-subj', f'/CN=block-{label}', '-out', csr)
        openssl('x509', '-req', '-in', csr, '-CA', str(directory/'ca.crt'), '-CAkey', str(directory/'ca.key'),
                '-CAcreateserial', '-out', cert, '-days', '14', '-sha256', '-extfile', str(extension))
        openssl('verify', '-CAfile', str(directory/'ca.crt'), '-verify_ip', '127.0.0.1', cert)
        ini = ConfigParser(interpolation=None)
        ini.read(Path(__file__).resolve().parents[1]/'deploy/hemlock.example.ini')
        ini['node'].update(node_id=f'block-{label}', role=role, database=str(directory/f'{label}.sqlite'),
                           peer_node_id=f'block-{peer}', peer_url=f'https://127.0.0.1:{peer_port}',
                           token_file=str(directory/'peer.token'), poll_seconds='0.2')
        ini['tls']['mode']='legacy_ca'
        ini['web'].update(host='127.0.0.1', port=str(port), tls='yes', cert=cert, key=key, ca=str(directory/'ca.crt'))
        ini['gobgp'].update(announcements='no', owner=f'64512,100,{1 if label == "a" else 2}')
        ini['protection']['protected_asns'] = ''
        ini['irr']['irr_command'] = str(fixture)
        ini['metadata'] = {'metadata_enabled':'no'}
        # Deliberately unusable proxies prove that replication stays direct.
        ini['proxy'].update(use_proxy='yes',http='http://127.0.0.1:9',https='http://127.0.0.1:9',no_proxy='')
        with (directory/f'{label}.ini').open('w') as output:
            ini.write(output)
    print(f'Lab files created in {directory}; no processes started. Announcements are disabled.')


if __name__ == '__main__':
    main()
