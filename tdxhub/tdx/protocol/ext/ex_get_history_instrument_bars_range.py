import struct
from collections import OrderedDict

from tdxhub.tdx.protocol.base import BaseParser


class GetHistoryInstrumentBarsRange(BaseParser):
    def __init__(self, *args, **kvargs):
        super().__init__(self, *args, **kvargs)
        self.seq_id = 1

    def setParams(self, market, code, date, date2):
        """

        :param market:
        :param code:
        :param date:
        :param date2:
        """
        pkg = bytearray.fromhex("01")
        pkg.extend(struct.pack("<B", self.seq_id))
        pkg.extend(bytearray.fromhex("38 92 00 01 16 00 16 00 0D 24"))

        pkg.extend(struct.pack("<B9s", market, code.encode("utf-8")))
        pkg.extend(bytearray.fromhex("07 00"))
        pkg.extend(struct.pack("<LL", date, date2))

        self.send_pkg = pkg
        self.seq_id += 1

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

    def parseResponse(self, body_buf):
        """

        :param body_buf:
        :return:
        """
        klines = []  # noqa
        pos = 12

        # 算了，前面不解析了，没太大用
        # (market, code) = struct.unpack("<B9s", body_buf[0: 10]

        (ret_count,) = struct.unpack("H", body_buf[pos : pos + 2])
        pos = pos + 2

        for _ in range(ret_count):
            (d1, d2, open_price, high, low, close, position, trade, settlementprice) = struct.unpack(
                "<HHffffIIf", body_buf[pos : pos + 32]
            )  # noqa
            pos += 32

            year, month, day = self._parse_date(d1)
            hour, minute = self._parse_time(d2)
            kline = OrderedDict(
                [
                    ("datetime", "%d-%02d-%02d %02d:%02d" % (year, month, day, hour, minute)),
                    ("year", year),
                    ("month", month),
                    ("day", day),
                    ("hour", hour),
                    ("minute", minute),
                    ("open", open_price),
                    ("high", high),
                    ("low", low),
                    ("close", close),
                    ("position", position),
                    ("trade", trade),
                    ("settlementprice", settlementprice),  # noqa
                ]
            )

            klines.append(kline)

        return klines
