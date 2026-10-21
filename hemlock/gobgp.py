"""GoBGP 4.10.0 gRPC adapter using a deliberately small wire-compatible schema.

Only the verified v4 API service and binary unicast path fields are used.
No generated bindings from a different major version are accepted.
"""

from dataclasses import asdict
import ipaddress
import hashlib
import struct
import threading

from .domain import Conflict, Invalid, prefix
from .reconcile import Path

API_VERSION = '4.10.0'


def messages():
    """Build our minimal v4 message projection; protobuf preserves unknown fields."""
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, timestamp_pb2
    descriptor = descriptor_pb2.FileDescriptorProto(name='hemlock_gobgp_v4.proto', package='api', syntax='proto3')
    descriptor.dependency.append('google/protobuf/timestamp.proto')
    definitions = {
        'Family': [('afi', 1, 'uint32'), ('safi', 2, 'uint32')],
        'Path': [('family', 9, 'Family'), ('no_implicit_withdraw', 8, 'bool'),
                 ('is_from_external', 14, 'bool'), ('neighbor_ip', 15, 'string'), ('uuid', 16, 'bytes'),
                 ('identifier', 18, 'uint32'),
                 ('nlri_binary', 20, 'bytes'), ('pattrs_binary', 21, 'bytes[]')],
        'Destination': [('prefix', 1, 'string'), ('paths', 2, 'Path[]')],
        'TableLookupPrefix': [('prefix', 1, 'string'), ('type', 2, 'uint32')],
        'ListPathRequest': [('prefixes', 4, 'TableLookupPrefix[]'), ('table_type', 1, 'uint32'), ('name', 2, 'string'), ('family', 3, 'Family'), ('enable_only_binary', 9, 'bool')],
        'ListPathResponse': [('destination', 1, 'Destination')],
        'AddPathRequest': [('table_type', 1, 'uint32'), ('path', 3, 'Path')],
        'AddPathResponse': [('uuid', 1, 'bytes')],
        'DeletePathRequest': [('table_type', 1, 'uint32'), ('family', 3, 'Family'), ('path', 4, 'Path'), ('uuid', 5, 'bytes')],
        'DeletePathResponse': [],
        'PeerState': [('description', 2, 'string'), ('local_asn', 3, 'uint32'),
                      ('neighbor_address', 5, 'string'), ('peer_asn', 6, 'uint32'),
                      ('session_state', 13, 'uint32'), ('admin_state', 15, 'uint32')],
        'TimersState': [('uptime', 6, 'google.protobuf.Timestamp')],
        'Timers': [('state', 2, 'TimersState')],
        'Peer': [('state', 5, 'PeerState'), ('timers', 6, 'Timers')],
        'ListPeerRequest': [('enable_advertised', 2, 'bool')],
        'ListPeerResponse': [('peer', 1, 'Peer')],
    }
    scalar = {'uint32': 13, 'bool': 8, 'string': 9, 'bytes': 12}
    for name, fields in definitions.items():
        msg = descriptor.message_type.add(name=name)
        for field_name, number, kind in fields:
            repeated = kind.endswith('[]')
            kind = kind.removesuffix('[]')
            field = msg.field.add(name=field_name, number=number, label=3 if repeated else 1, type=scalar.get(kind, 11))
            if kind not in scalar:
                field.type_name = '.' + kind if kind.startswith('google.protobuf.') else '.api.' + kind
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(timestamp_pb2.DESCRIPTOR.serialized_pb)
    pool.Add(descriptor)
    return {name: message_factory.GetMessageClass(pool.FindMessageTypeByName('api.' + name)) for name in definitions}


def attribute(code, payload, flags):
    if len(payload) > 255:
        return bytes([flags | 0x10, code]) + struct.pack('!H', len(payload)) + payload
    return bytes([flags, code, len(payload)]) + payload


def nlri(candidate):
    network = ipaddress.ip_network(prefix(candidate))
    return bytes([network.prefixlen]) + network.network_address.packed[:(network.prefixlen + 7)//8]


def unicast_attributes(candidate, attrs):
    hop, local_pref, communities, owner = attrs
    network = ipaddress.ip_network(prefix(candidate))
    next_hop = ipaddress.ip_address(hop)
    if next_hop.version != network.version:
        raise Invalid('Next-hop address family mismatch')
    result = [attribute(1, b'\x00', 0x40), attribute(2, b'', 0x40),
              attribute(5, struct.pack('!I', local_pref), 0x40)]
    values = []
    for community in communities:
        high, low = (int(n) for n in community.split(':'))
        if not 0 <= high <= 65535 or not 0 <= low <= 65535:
            raise Invalid('Invalid standard community')
        values.append((high << 16) | low)
    result.append(attribute(8, b''.join(struct.pack('!I', n) for n in values), 0xc0))
    result.append(attribute(32, struct.pack('!III', *owner), 0xc0))
    if network.version == 4:
        result.append(attribute(3, next_hop.packed, 0x40))
    else:
        reach = struct.pack('!HBB', 2, 1, len(next_hop.packed)) + next_hop.packed + b'\x00' + nlri(candidate)
        result.append(attribute(14, reach, 0x80))
    return result


def inspect_attributes(raw_attributes):
    hop, local_pref, communities, owners = '', 0, [], []
    for raw in raw_attributes:
        if len(raw) < 3:
            raise Invalid('Truncated path attribute')
        extended = bool(raw[0] & 0x10)
        head = 4 if extended else 3
        length = int.from_bytes(raw[2:head], 'big')
        if len(raw) != head + length:
            raise Invalid('Invalid path attribute length')
        code, data = raw[1], raw[head:]
        if code == 3 and length == 4:
            hop = str(ipaddress.ip_address(data))
        elif code == 5 and length == 4:
            local_pref = struct.unpack('!I', data)[0]
        elif code == 8:
            if length % 4:
                raise Invalid('Invalid communities')
            communities.extend(f'{n >> 16}:{n & 65535}' for (n,) in struct.iter_unpack('!I', data))
        elif code == 32:
            if length % 12:
                raise Invalid('Invalid ownership communities')
            owners.extend(struct.iter_unpack('!III', data))
        elif code == 14 and length >= 5:
            afi, safi, hoplen = struct.unpack('!HBB', data[:4])
            if afi == 2 and safi == 1 and hoplen in (16, 32) and len(data) >= 4 + hoplen + 1:
                hop = str(ipaddress.ip_address(data[4:20]))
    return hop, local_pref, tuple(sorted(communities)), owners


class GoBGP:
    def __init__(self, config, protection_check=None):
        self.config = config
        self.protection_check = protection_check
        self.identifier = int.from_bytes(hashlib.sha256(struct.pack('!III', *config.owner)).digest()[:4], 'big') or 1
        self.channel = None
        self.lock = threading.Lock()

    def initialize(self):
        with self.lock:
            if self.channel is not None:
                return
            import grpc
            self.m = messages()
            channel = grpc.insecure_channel(self.config.grpc_target, options=[('grpc.enable_http_proxy', 0), ('grpc.max_receive_message_length', 64*1024*1024)])
            self.list_paths = channel.unary_stream('/api.GoBgpService/ListPath', request_serializer=lambda x: x.SerializeToString(), response_deserializer=self.m['ListPathResponse'].FromString)
            self.add_path = channel.unary_unary('/api.GoBgpService/AddPath', request_serializer=lambda x: x.SerializeToString(), response_deserializer=self.m['AddPathResponse'].FromString)
            self.delete_path = channel.unary_unary('/api.GoBgpService/DeletePath', request_serializer=lambda x: x.SerializeToString(), response_deserializer=self.m['DeletePathResponse'].FromString)
            self.list_peers = channel.unary_stream('/api.GoBgpService/ListPeer', request_serializer=lambda x: x.SerializeToString(), response_deserializer=self.m['ListPeerResponse'].FromString)
            self.channel = channel

    def paths(self, candidate=None):
        self.initialize()
        result = []
        for afi in ((1 if ipaddress.ip_network(candidate).version == 4 else 2,) if candidate else (1, 2)):
            request = self.m['ListPathRequest'](table_type=1, family=self.m['Family'](afi=afi, safi=1), enable_only_binary=True)
            if candidate:
                request.prefixes.add(prefix=prefix(candidate), type=1)
            for response in self.list_paths(request, timeout=self.config.timeout):
                for item in response.destination.paths:
                    hop, pref, communities, owners = inspect_attributes(item.pattrs_binary)
                    marker = self.config.owner if self.config.owner in owners and item.identifier == self.identifier else ()
                    local = not item.is_from_external and not item.neighbor_ip
                    result.append(Path(item.uuid.hex(), prefix(response.destination.prefix), hop, pref, communities,
                                       marker, local, item.identifier, item.SerializeToString()))
        return result

    def add(self, candidate, attrs):
        if not self.config.announcements:
            raise Conflict('Announcements are disabled')
        self.initialize()
        # Avoid replacing a path injected by a different application at the same NLRI.
        if any(p.prefix == candidate and p.local and p.owner != self.config.owner for p in self.paths(candidate)):
            raise Conflict('Foreign locally injected path already exists for this prefix')
        afi = ipaddress.ip_network(candidate).version
        path = self.m['Path'](family=self.m['Family'](afi=1 if afi == 4 else 2, safi=1),
                              identifier=self.identifier, nlri_binary=nlri(candidate),
                              pattrs_binary=unicast_attributes(candidate, attrs))
        if self.protection_check is not None:
            self.protection_check(candidate)
        response = self.add_path(self.m['AddPathRequest'](table_type=1, path=path), timeout=self.config.timeout)
        return response.uuid.hex()

    def delete(self, path):
        if not self.config.announcements or not path.local or path.owner != self.config.owner or path.identifier != self.identifier:
            raise Conflict('Refusing unowned or disabled route withdrawal')
        self.initialize()
        candidates = [p for p in self.paths(path.prefix) if p.key == path.key and p.local]
        if len(candidates) != 1 or candidates[0].owner != self.config.owner:
            raise Conflict('Owned path is absent or ambiguous; refusing withdrawal')
        observed = self.m['Path'].FromString(candidates[0].wire)
        family = self.m['Family'](afi=1 if ipaddress.ip_network(path.prefix).version == 4 else 2, safi=1)
        # v4.10.0 ListPath omits UUID. A nonempty observed path selects this NLRI,
        # local source and stable path identifier; never send an empty delete.
        self.delete_path(self.m['DeletePathRequest'](table_type=1, family=family, path=observed), timeout=self.config.timeout)

    def observe(self):
        paths = [{k:v for k,v in asdict(p).items() if k != 'wire'} for p in self.paths()]
        peers, exports = [], {}
        for response in self.list_peers(self.m['ListPeerRequest'](enable_advertised=True), timeout=self.config.timeout):
            state = response.peer.state
            address = state.neighbor_address
            peers.append({'address': address, 'asn': state.peer_asn, 'local_asn': state.local_asn,
                          'session_state': state.session_state, 'admin_state': state.admin_state,
                          'description': state.description,
                          'established_at': response.peer.timers.state.uptime.seconds or None})
            try:
                prefixes = []
                truncated = False
                for afi in (1, 2):
                    request = self.m['ListPathRequest'](table_type=4, name=address,
                                                        family=self.m['Family'](afi=afi, safi=1), enable_only_binary=True)
                    for destination in self.list_paths(request, timeout=self.config.timeout):
                        if len(prefixes) >= 100000:
                            truncated = True
                            break
                        prefixes.append(destination.destination.prefix)
                exports[address] = {'prefixes': prefixes, 'truncated': truncated, 'source': 'GoBGP Adj-RIB-Out'}
            except Exception:
                exports[address] = {'error': 'Adj-RIB-Out unavailable'}
        return {'paths': paths, 'peers': peers, 'export': exports,
                'limitations': 'Local RIB and Adj-RIB-Out do not confirm downstream router acceptance',
                'api_version': API_VERSION}

    def close(self):
        if self.channel is not None:
            self.channel.close()
