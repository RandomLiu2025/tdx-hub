import struct
from collections import OrderedDict

from tdxhub.tdx.protocol.base import BaseParser


class GetHistoryMinuteTimeData(BaseParser):
    def setParams(self, market, code, date):
        pkg = bytearray.fromhex("01 01 30 00 01 01 10 00 10 00 0c 24")
        pkg.extend(struct.pack("<IB9s", date, market, code.encode("utf-8")))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        pos = 0

        market, code, _, num = struct.unpack("<B9s8sH", body_buf[pos : pos + 20])

        pos += 20

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
