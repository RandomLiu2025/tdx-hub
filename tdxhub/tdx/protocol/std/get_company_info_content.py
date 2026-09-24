import struct

from tdxhub.tdx.protocol.base import BaseParser


class GetCompanyInfoContent(BaseParser):
    def setParams(self, market, code, filename, start, length):
        """

        :param market:
        :param code:
        :param filename:
        :param start:
        :param length:
        """
        if type(code) is str:
            code = code.encode("utf-8")

        if type(filename) is str:
            filename = filename.encode("utf-8")

        if len(filename) != 80:
            filename = filename.ljust(80, b"\x00")

        pkg = bytearray.fromhex("0c 07 10 9c 00 01 68 00 68 00 d0 02")
        pkg.extend(struct.pack("<H6sH80sIII", market, code, 0, filename, start, length, 0))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """

        :param body_buf:
        :return:
        """
        pos = 0

        _, length = struct.unpack("<10sH", body_buf[:12])

        pos += 12

        content = body_buf[pos : pos + length]
        content = content.decode("gbk", "ignore")

        return content
