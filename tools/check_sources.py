"""Read-only source checks using explicitly selected, local-only targets/config."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hemloc.config import load
from hemloc.domain import asn,prefix
from hemloc.irr import IRR,Metadata
from hemloc.service import Service
from hemloc.store import Store


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True,help='Private local configuration; never use a committed live configuration')
    parser.add_argument('--asn',required=True,type=asn,help='Operator-selected ASN for read-only external checks')
    parser.add_argument('--ip',required=True,help='Operator-selected address for metadata lookup')
    args=parser.parse_args();address=prefix(args.ip)
    config=replace(load(args.config),announcements=False,protected_asns=(args.asn,))
    report={}
    with tempfile.TemporaryDirectory(prefix='hemloc-sources-') as tmp:
        service=Service(Store(replace(config,database=str(Path(tmp)/'sources.sqlite'))))
        for name,action in [('metadata_asn',lambda:Metadata(config).asn_name(args.asn)),
                            ('metadata_ip',lambda:Metadata(config).origins(address)),
                            ('protected_asn',lambda:IRR(config).expand(args.asn))]:
            start=time.monotonic()
            try:
                result=action()
                if name=='protected_asn':
                    service.grow_protection(args.asn,result)
                    report[name]={'ok':True,'prefixes':len(result),'ready':service.protection_ready()}
                else:report[name]={'ok':True,'has_metadata':bool(result)}
            except Exception as exc:report[name]={'ok':False,'error_type':type(exc).__name__}
            report[name]['seconds']=round(time.monotonic()-start,3)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
