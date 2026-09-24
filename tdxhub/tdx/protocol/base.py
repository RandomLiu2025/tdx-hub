import abc
import datetime
import struct
import zlib

from tdxhub.tdx.deadline import deadline_lock, socket_budget
from tdxhub.tdx.errors import (
    ProtocolError,
    ResponseHeaderRecvFails,
    ResponseRecvFails,
    SendPkgNotReady,
    SendRequestPkgFails,
    SocketClientNotReady,
)

RSP_HEADER_LEN = 0x10


class BaseParser:
    def __init__(self, client, lock=None):
        """

        :rtype: object
        """

        self.send_pkg = None
        self.data = None

        self.rsp_header_len = RSP_HEADER_LEN
        self.rsp_header = None
        self.rsp_body = None

        self.client = client
        self.lock = lock or None

        self.category = None

    def setParams(self, *args, **xargs):  # noqa
        """
        构建请求
        :return:
        """
        pass

    @abc.abstractmethod
    def parseResponse(self, body_buf):  # noqa
        """
        解析结果
        :param body_buf:
        """
        pass

    @staticmethod
    def _parse_date(num):
        """

        :param num:
        :return:
        """
        month = (num % 2048) // 100
        year = num // 2048 + 2004
        day = (num % 2048) % 100

        return year, month, day

    @staticmethod
    def _parse_time(num):
        """

        :param num:
        :return:
        """
        return (num // 60), (num % 60)

    @staticmethod
    def _cal_price1000(base_p, diff):
        return float(base_p + diff) / 1000

    def setup(self):
        pass

    def call_api(self):
        """

        :return:
        """
        with deadline_lock(self.lock):
            return self._call_api()

    def _error(self, message, error_type=ProtocolError):
        try:
            endpoint = self.client.getpeername()
        except (AttributeError, OSError):
            endpoint = "unknown"
        return error_type(f"server={endpoint} command={type(self).__name__} {message}")

    def _recv_exact(self, size, error_type):
        data = bytearray()
        while len(data) < size:
            try:
                with socket_budget(self.client):
                    chunk = self.client.recv(size - len(data))
            except OSError as exc:
                raise self._error(f"receive expected={size} received={len(data)}: {exc}", error_type) from exc
            self.client.recv_pkg_num += 1
            self.client.recv_pkg_bytes += len(chunk)
            self.client.last_api_recv_bytes += len(chunk)
            if not chunk:
                raise self._error(f"receive expected={size} received={len(data)} EOF", error_type)
            data.extend(chunk)
        return bytes(data)

    def _call_api(self):
        self.setup()
        if not self.client:
            raise SocketClientNotReady("socket client not ready")
        if not self.send_pkg:
            raise SendPkgNotReady("send pkg not ready")

        self.client.last_api_send_bytes = 0
        self.client.last_api_recv_bytes = 0
        self.rsp_header = self.rsp_body = None
        if not self.client.first_pkg_send_time:
            self.client.first_pkg_send_time = datetime.datetime.now()
        sent = 0
        while sent < len(self.send_pkg):
            try:
                with socket_budget(self.client):
                    count = self.client.send(self.send_pkg[sent:])
            except OSError as exc:
                raise self._error(
                    f"send expected={len(self.send_pkg)} sent={sent}: {exc}", SendRequestPkgFails
                ) from exc
            if count <= 0 or count > len(self.send_pkg) - sent:
                raise self._error(
                    f"send expected={len(self.send_pkg)} sent={sent} invalid_count={count}", SendRequestPkgFails
                )
            sent += count
            self.client.send_pkg_num += 1
            self.client.send_pkg_bytes += count
            self.client.last_api_send_bytes += count

        head = self._recv_exact(self.rsp_header_len, ResponseHeaderRecvFails)
        self.rsp_header = head
        _, _, _, zip_size, unzip_size = struct.unpack("<IIIHH", head)
        body = self._recv_exact(zip_size, ResponseRecvFails)
        if zip_size != unzip_size:
            try:
                decoder = zlib.decompressobj()
                # Header lengths are uint16. Bound decompression before allocating an untrusted body.
                body = decoder.decompress(body, unzip_size + 1)
                if len(body) != unzip_size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    raise ValueError(f"expected={unzip_size} actual={len(body)} or incomplete/trailing stream")
            except (zlib.error, ValueError) as exc:
                raise self._error(f"decompress zip_size={zip_size} unzip_size={unzip_size}: {exc}") from exc
        self.rsp_body = body
        self._parse_offset = 0
        try:
            return self.parseResponse(body)
        except (struct.error, IndexError, ValueError) as exc:
            raise self._error(
                f"parse offset={self._parse_offset} body_length={len(body)} prefix={body[:16].hex()}: {exc}"
            ) from exc
