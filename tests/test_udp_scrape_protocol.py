import asyncio
import struct
import random
import pytest

from main import _udp_scrape_one


class MockTrackerProtocol(asyncio.DatagramProtocol):
    def __init__(self, seeders_list=None):
        super().__init__()
        self.transport = None
        self.conn_id = random.getrandbits(64)
        # default seeders per hash (if list shorter, reuse last value)
        self.seeders_list = seeders_list or [7]

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        # If data length == 16 and looks like a connect request (QII)
        try:
            if len(data) >= 16:
                # Try unpack as connect request: QII
                magic, action, trans = struct.unpack('!QII', data[:16])
                if action == 0:
                    # connect response: IIQ (action, trans, conn_id)
                    resp = struct.pack('!IIQ', 0, trans, self.conn_id)
                    self.transport.sendto(resp, addr)
                    return
            # Otherwise treat it as scrape: QII + (20*nhashes)
            # the client sends conn_id (8), action=2 (4), trans (4), then hashes
            if len(data) >= 16:
                conn_id, action, trans = struct.unpack('!QII', data[:16])
                if action == 2:
                    hashes_data = data[16:]
                    n = len(hashes_data) // 20
                    resp_header = struct.pack('!II', 2, trans)
                    body = b''
                    for i in range(n):
                        s = self.seeders_list[i] if i < len(self.seeders_list) else self.seeders_list[-1]
                        # seeders, leechers, completed
                        body += struct.pack('!III', s, 0, 0)
                    self.transport.sendto(resp_header + body, addr)
                    return
        except Exception:
            # ignore errors
            return


@pytest.mark.asyncio
async def test_udp_scrape_one_local_server():
    loop = asyncio.get_event_loop()
    # prepare the server on localhost:0 (random free port)
    protocol = MockTrackerProtocol(seeders_list=[5, 10])
    transport, _ = await loop.create_datagram_endpoint(lambda: protocol, local_addr=('127.0.0.1', 0))
    try:
        sockname = transport.get_extra_info('sockname')
        port = sockname[1]
        # choose two valid 20-byte hex hashes
        hash_a = 'a' * 40  # 20 bytes of 0xaa
        hash_b = 'b' * 40  # 20 bytes of 0xbb
        res = await _udp_scrape_one('127.0.0.1', port, [hash_a, hash_b], timeout=2.0)
        # Expect mapping of both hashes to the seeders_list indices 5 and 10
        assert res.get(hash_a.lower()) == 5 or res.get(hash_a.upper()) == 5
        assert res.get(hash_b.lower()) == 10 or res.get(hash_b.upper()) == 10
    finally:
        transport.close()
