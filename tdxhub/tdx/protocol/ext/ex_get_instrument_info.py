import struct
from collections import OrderedDict

from tdxhub.tdx.protocol.base import BaseParser


class GetInstrumentInfo(BaseParser):
    def setParams(self, start, count=100):
        """

        :param start:
        :param count:
        """
        pkg = bytearray.fromhex("01 04 48 67 00 01 08 00 08 00 f5 23")
        pkg.extend(struct.pack("<IH", start, count))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """

        :param body_buf:
        :return:
        """
        pos = 0
        start, count = struct.unpack("<IH", body_buf[:6])

        pos += 6
        result = []

        for _ in range(count):
            category, market, _, code_raw, name_raw, desc_raw = struct.unpack("<BB3s9s17s9s", body_buf[pos : pos + 40])

            code = code_raw.decode("gbk", "ignore").rstrip("\x00")
            name = name_raw.decode("gbk", "ignore").rstrip("\x00")
            desc = desc_raw.decode("gbk", "ignore").rstrip("\x00")

            line = OrderedDict(
                [
                    ("category", category),
                    ("market", market),
                    ("code", code),
                    ("name", name),
                    ("desc", desc),
                ]
            )

            result.append(line)

            pos += 64

        return result
