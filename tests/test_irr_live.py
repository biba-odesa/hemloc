"""Installed bgpq4 against a deterministic loopback IRRD protocol fixture."""

from dataclasses import replace
import shutil
import socketserver
import threading
import unittest

from hemloc.config import Config
from hemloc.irr import IRR, IRRError


@unittest.skipUnless(shutil.which('bgpq4'),'bgpq4 is not installed')
class IRRLiveTests(unittest.TestCase):
    def expand(self, empty=False, malformed=False):
        queries=[]
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(3)
                while line:=self.rfile.readline():
                    query=line.decode().strip().lower()
                    queries.append(query)
                    if query=='!!':
                        continue
                    if query=='!q':
                        break
                    if query.startswith(('!g','!6')):
                        if empty:
                            self.wfile.write(b'C\n')
                        else:
                            data=b'not-a-prefix\n' if malformed else (b'2001:db8::/32\n' if query.startswith('!6') else b'192.0.2.0/24 198.51.100.0/24\n')
                            self.wfile.write(b'A'+str(len(data)).encode()+b'\n'+data+b'C\n')
                    else:
                        self.wfile.write(b'C\n')
                    self.wfile.flush()
        with socketserver.TCPServer(('127.0.0.1',0),Handler) as server:
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':0.05})
            thread.start()
            try:
                config=replace(Config(),irr_server=f'127.0.0.1:{server.server_address[1]}',irr_sources='RADB',timeout=3)
                result=IRR(config).expand(64500)
            finally:
                server.shutdown()
                thread.join()
        return result,queries

    def test_real_ipv4_ipv6_private_asn_and_format(self):
        result,queries=self.expand()
        self.assertEqual(set(result),{'192.0.2.0/24','198.51.100.0/24','2001:db8::/32'})
        self.assertIn('!gas64500',queries)
        self.assertIn('!6as64500',queries)

    def test_real_empty_and_malformed_responses(self):
        self.assertEqual(self.expand(empty=True)[0],[])
        with self.assertRaises(IRRError):
            self.expand(malformed=True)


if __name__ == '__main__':
    unittest.main()
