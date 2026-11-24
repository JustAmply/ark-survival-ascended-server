"""Command replies over a real stream, including coalesced and partial frames."""

from concurrent.futures import ThreadPoolExecutor
import socket
import struct

import pytest

from asa_ctrl.common.errors import RconDeliveryUnknownError
from asa_ctrl.core.rcon import RconClient


def recv_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.recv(size - len(data))
        assert part, "client closed before sending its request"
        data.extend(part)
    return data


def request(stream):
    size, = struct.unpack("<I", recv_exact(stream, 4))
    data = recv_exact(stream, size)
    return struct.unpack_from("<ii", data), data[8:-2]


def frame(request_id, kind, body):
    return struct.pack("<Iii", len(body) + 10, request_id, kind) + body + b"\0\0"


@pytest.mark.parametrize("truncated", [False, True])
def test_multipart_command_reply(truncated):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(3)

        def serve():
            with listener.accept()[0] as stream:
                stream.settimeout(3)
                (auth_id, kind), _ = request(stream)
                assert kind == 3
                stream.sendall(frame(auth_id, 2, b""))
                (request_id, kind), body = request(stream)
                assert (kind, body) == (2, b"ListPlayers")
                first = frame(request_id, 0, b"a" * 3200 + b"\xc3")
                second = frame(request_id, 0, b"\xa4" + b"b" * 3200)
                stream.sendall(first + (second[:-3] if truncated else second))
                if not truncated:
                    (next_id, kind), body = request(stream)
                    assert next_id != request_id
                    assert (kind, body) == (2, b"GetChat")
                    stream.sendall(frame(next_id, 0, b""))

        with ThreadPoolExecutor(max_workers=1) as worker:
            peer = worker.submit(serve)
            with RconClient(port=listener.getsockname()[1], password="fixture", retry_count=0) as client:
                if truncated:
                    with pytest.raises(RconDeliveryUnknownError):
                        client.execute_command("ListPlayers")
                else:
                    assert client.execute_command("ListPlayers") == "a" * 3200 + "ä" + "b" * 3200
                    assert client.execute_command("GetChat") == ""
            peer.result()
