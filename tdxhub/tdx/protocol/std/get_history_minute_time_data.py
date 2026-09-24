import struct
from collections import OrderedDict

from tdxhub.tdx.codec import get_price, get_security_coefficient
from tdxhub.tdx.protocol.base import BaseParser


class GetHistoryMinuteTimeData(BaseParser):
    def __init__(self, client, lock=None):
        super().__init__(client, lock)
        self.coefficient = 0.001

    def setParams(self, market, code, date):
        """
        设置参数
        :param market: 0/1 股票市场
        :param code: '000001' 股票代码
        :param date: 20161201  类似这样的整型
        :return:
        """
        self.coefficient = get_security_coefficient(market=market, code=code)

        if (type(date) is str) or (type(date) is bytes):
            date = int(date)

        if type(code) is str:
            code = code.encode("utf-8")

        pkg = bytearray.fromhex("0c 01 30 00 01 01 0d 00 0d 00 b4 0f")
        pkg.extend(struct.pack("<IB6s", date, market, code))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """

        :param body_buf:
        :return:
        """
        pos = 0

        (num,) = struct.unpack("<H", body_buf[:2])
        last_price = 0

        # 跳过了4个字节，实在不知道是什么意思
        pos += 6
        prices = []

        for _ in range(num):
            price_raw, pos = get_price(body_buf, pos)
            reversed1, pos = get_price(body_buf, pos)

            vol, pos = get_price(body_buf, pos)
            last_price = last_price + price_raw

            price = OrderedDict([("price", float(last_price) * self.coefficient), ("vol", vol)])
            prices.append(price)

        return prices
