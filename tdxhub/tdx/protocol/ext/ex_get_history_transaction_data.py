import datetime
import struct
from collections import OrderedDict

from tdxhub.tdx.protocol.base import BaseParser


class GetHistoryTransactionData(BaseParser):
    date = None

    def setParams(self, market, code, date, start, count):
        if type(code) is str:
            code = code.encode("utf-8")

        pkg = bytearray.fromhex("01 01 30 00 02 01 16 00 16 00 06 24")
        pkg.extend(struct.pack("<IB9siH", date, market, code, start, count))

        self.send_pkg = pkg
        self.date = date

    def parseResponse(self, body_buf):
        pos = 0
        market, code, _, num = struct.unpack("<B9s4sH", body_buf[pos : pos + 16])

        pos += 16
        result = []

        for _ in range(num):
            raw_time, price, volume, zengcang, direction = struct.unpack("<HIIiH", body_buf[pos : pos + 16])

            pos += 16
            year = self.date // 10000
            month = self.date % 10000 // 100
            day = self.date % 100
            hour = raw_time // 60
            minute = raw_time % 60
            second = direction % 10000
            nature = direction  # 为了老用户接口的兼容性，已经转换为使用 nature_value
            value = direction // 10000
            nature_name = "换手"

            # 对于大于59秒的值，属于无效数值
            if second > 59:
                second = 0

            date = datetime.datetime(year, month, day, hour, minute, second)

            if value == 0:
                direction = 1
                if zengcang > 0:
                    if volume > zengcang:
                        nature_name = "多开"
                    elif volume == zengcang:
                        nature_name = "双开"
                elif zengcang == 0:
                    nature_name = "多换"
                else:
                    if volume == -zengcang:
                        nature_name = "双平"
                    else:
                        nature_name = "空平"
            elif value == 1:
                direction = -1
                if zengcang > 0:
                    if volume > zengcang:
                        nature_name = "空开"
                    elif volume == zengcang:
                        nature_name = "双开"
                elif zengcang == 0:
                    nature_name = "空换"
                else:
                    if volume == -zengcang:
                        nature_name = "双平"
                    else:
                        nature_name = "多平"
            else:
                direction = 0
                if zengcang > 0:
                    if volume > zengcang:
                        nature_name = "开仓"
                    elif volume == zengcang:
                        nature_name = "双开"
                elif zengcang < 0:
                    if volume > -zengcang:
                        nature_name = "平仓"
                    elif volume == -zengcang:
                        nature_name = "双平"
                else:
                    nature_name = "换手"

            if market in [31, 48]:
                if nature == 0:
                    direction = 1
                    nature_name = "B"
                elif nature == 256:
                    direction = -1
                    nature_name = "S"
                else:  # 512
                    direction = 0
                    nature_name = ""

            result.append(
                OrderedDict(
                    [
                        ("date", date),
                        ("hour", hour),
                        ("minute", minute),
                        ("price", price),
                        ("volume", volume),
                        ("zengcang", zengcang),
                        ("natrue_name", nature_name),
                        (
                            "nature_name",
                            nature_name,
                        ),  # 修正了nature_name的拼写错误(natrue), 为了保持兼容性，原有的natrue_name还会保留一段时间
                        ("direction", direction),
                        ("nature", nature),
                    ]
                )
            )

        return result
