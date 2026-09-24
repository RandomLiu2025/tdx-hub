"""Transport boundaries are byte streams, not one recv per packet."""

import struct
import zlib

import pytest

from tdxhub.tdx.client import StandardClient
from tdxhub.tdx.errors import TdxFunctionCallError
from tdxhub.tdx.protocol.base import ResponseHeaderRecvFails, ResponseRecvFails
from tdxhub.tdx.protocol.raw_parser import RawParser


class StreamSocket:
    def __init__(self, data, *, chunk=65535, send_chunk=65535):
        self.data = bytearray(data)
        self.chunk = chunk
        self.send_chunk = send_chunk
        self.sent = bytearray()
        self.send_pkg_num = self.send_pkg_bytes = self.last_api_send_bytes = 0
        self.recv_pkg_num = self.recv_pkg_bytes = self.last_api_recv_bytes = 0
        self.first_pkg_send_time = None

    def getpeername(self):
        return ("127.0.0.1", 7709)

    def send(self, data):
        count = min(len(data), self.send_chunk)
        self.sent.extend(data[:count])
        return count

    def recv(self, size):
        count = min(size, self.chunk, len(self.data))
        data = bytes(self.data[:count])
        del self.data[:count]
        return data


def frame(body, unpacked=None):
    return struct.pack("<IIIHH", 0, 0, 0, len(body), len(body) if unpacked is None else unpacked) + body


@pytest.mark.parametrize("chunk", [1, 3, 16, 65535])
def test_fragmented_transport_and_short_sends(chunk):
    sock = StreamSocket(frame(b"payload") + frame(b"next"), chunk=chunk, send_chunk=2)
    parser = RawParser(sock)
    parser.setParams(b"request")
    assert parser.call_api() == b"payload"
    assert bytes(sock.sent) == b"request"
    assert sock.last_api_send_bytes == 7
    assert sock.last_api_recv_bytes == 23
    assert parser.call_api() == b"next"
    assert bytes(sock.sent) == b"requestrequest"
    assert sock.send_pkg_bytes == 14


@pytest.mark.parametrize("data,error", [(b"bad", ResponseHeaderRecvFails), (frame(b"abc")[:-1], ResponseRecvFails)])
def test_truncation_has_endpoint_and_command_context(data, error):
    parser = RawParser(StreamSocket(data, chunk=1))
    parser.setParams(b"request")
    with pytest.raises(error, match=r"127.0.0.1.*7709.*RawParser.*expected"):
        parser.call_api()


@pytest.mark.parametrize(
    "body,size",
    [
        (zlib.compress(b"abc"), 5),
        (b"bad zip", 100),
        (zlib.compress(b"abc")[:-1], 3),
        (zlib.compress(b"abc") + b"trailing", 3),
    ],
)
def test_malformed_compression_is_protocol_failure(body, size):
    parser = RawParser(StreamSocket(frame(body, size)))
    parser.setParams(b"request")
    with pytest.raises(TdxFunctionCallError, match="decompress"):
        parser.call_api()


def test_zero_length_raw_frame_is_not_socket_disconnect():
    parser = RawParser(StreamSocket(frame(b"")))
    parser.setParams(b"request")
    assert parser.call_api() == b""


def test_short_bar_response_is_contextual_protocol_error():
    api = StandardClient(auto_retry=False, raise_exception=True)
    api.client = StreamSocket(frame(bytes.fromhex("2003")))
    with pytest.raises(TdxFunctionCallError, match=r"GetSecurityBarsCmd.*offset=2.*body_length=2") as caught:
        api.get_security_bars(9, 2, "920001", 0, 1)
    assert caught.value.__cause__ is not None
