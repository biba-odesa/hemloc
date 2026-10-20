"""Verify the minimal adapter projection against pinned upstream v4 descriptors."""

import argparse
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from hemloc.gobgp import API_VERSION,messages


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',default='var/gobgp-schema')
    args=parser.parse_args()
    directory=Path(args.directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    seen=set()
    def fetch(name):
        if name in seen or name.startswith('google/protobuf/'):
            return
        relative=PurePosixPath(name)
        if '..' in relative.parts or not name.startswith('api/') or relative.suffix!='.proto' or len(seen)>=64:
            raise ValueError('Unexpected upstream import')
        seen.add(name)
        url=f'https://raw.githubusercontent.com/osrg/gobgp/v{API_VERSION}/proto/{name}'
        with urlopen(url,timeout=20) as response:
            raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:
            raise ValueError('Upstream proto too large')
        path=directory/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
        for imported in re.findall(r'^import\s+"([^"]+)"',raw.decode(),re.MULTILINE):
            fetch(imported)
    fetch('api/gobgp.proto')
    import grpc_tools
    from grpc_tools import protoc
    from google.protobuf import descriptor_pb2,descriptor_pool
    standard=Path(grpc_tools.__file__).parent/'_proto'
    result=protoc.main(['protoc',f'-I{directory}',f'-I{standard}','--include_imports',
                       f'--descriptor_set_out={directory / "api.pb"}','api/gobgp.proto'])
    if result:
        raise RuntimeError('Descriptor compilation failed')
    files=descriptor_pb2.FileDescriptorSet.FromString((directory/'api.pb').read_bytes())
    pool=descriptor_pool.DescriptorPool()
    for file in files.file:
        pool.Add(file)
    count=0
    for name,projected in messages().items():
        upstream=pool.FindMessageTypeByName('api.'+name)
        for field in projected.DESCRIPTOR.fields:
            original=upstream.fields_by_name[field.name]
            assert field.number==original.number,(name,field.name,'field number')
            assert field.is_repeated==original.is_repeated,(name,field.name,'cardinality')
            assert field.type==original.type or (field.type==13 and original.type==14),(name,field.name,'wire type')
            if field.message_type:
                assert field.message_type.full_name==original.message_type.full_name
            count+=1
    service=pool.FindServiceByName('api.GoBgpService')
    for method,streaming in [('AddPath',False),('DeletePath',False),('ListPath',True),('ListPeer',True)]:
        rpc=service.methods_by_name[method]
        assert rpc.input_type.full_name=='api.'+method+'Request'
        assert rpc.output_type.full_name=='api.'+method+'Response'
        assert rpc.server_streaming==streaming and not rpc.client_streaming
    print(f'GoBGP {API_VERSION}: {len(messages())} projected messages / {count} fields / 4 RPCs match pinned descriptors.')
    print('Enum fields intentionally use the same nonnegative varint wire representation.')


if __name__=='__main__':
    main()
