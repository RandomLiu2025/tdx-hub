import struct

from tdxhub.tdx.protocol.base import BaseParser


class GetInstrumentCount(BaseParser):
    def setup(self):
        self.send_pkg = bytearray.fromhex("01 03 48 66 00 01 02 00 02 00 f0 23")

    def parseResponse(self, body_buf):
        (num,) = struct.unpack("<I", body_buf[19 : 19 + 4])

        return num
