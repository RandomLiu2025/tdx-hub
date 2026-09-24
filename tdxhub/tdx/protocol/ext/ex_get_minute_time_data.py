import struct
from collections import OrderedDict

from tdxhub.tdx.protocol.base import BaseParser


class GetMinuteTimeData(BaseParser):
    def setParams(self, market, code):
        """

        :param market:
        :param code:
        """
        pkg = bytearray.fromhex("01 07 08 00 01 01 0c 00 0c 00 0b 24")
        pkg.extend(struct.pack("<B9s", market, code.encode("utf-8")))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """

        :param body_buf:
        :return:
        """
        pos = 0

        market, code, num = struct.unpack("<B9sH", body_buf[pos : pos + 12])
        pos += 12

        result = []

        for _ in range(num):
            raw_time, price, avg_price, volume, amount = struct.unpack("<HffII", body_buf[pos : pos + 18])
            pos += 18

            hour = raw_time // 60
            minute = raw_time % 60

            result.append(
                OrderedDict(
                    [
                        ("hour", hour),
                        ("minute", minute),
                        ("price", price),
                        ("avg_price", avg_price),
                        ("volume", volume),
                        ("open_interest", amount),
                    ]
                )
            )

        return result
