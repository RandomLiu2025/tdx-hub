import struct
from collections import OrderedDict

from tdxhub.tdx.logger import logger
from tdxhub.tdx.protocol.base import BaseParser


class GetCompanyInfoCategory(BaseParser):
    def setParams(self, market, code):
        """
        设置参数
        :param market: 市场
        :param code: 代码
        """
        if type(code) is str:
            code = code.encode("utf-8")

        pkg = bytearray.fromhex("0c 0f 10 9b 00 01 0e 00 0e 00 cf 02")
        pkg.extend(struct.pack("<H6sI", market, code, 0))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """
        解析结果
        :param body_buf:
        :return:
        """
        pos = 0

        (num,) = struct.unpack("<H", body_buf[:2])

        pos += 2

        category = []

        def get_str(b):
            """
            :param b:
            :return:
            """
            p = b.find(b"\x00")

            if p != -1:
                b = b[0:p]

            try:
                n = b.decode("gbk", "ignore")
            except Exception as e:
                logger.exception(e)
                n = "unknown_str"

            return n

        for _ in range(num):
            name, filename, start, length = struct.unpack("<64s80sII", body_buf[pos : pos + 152])
            pos += 152

            entry = OrderedDict(
                [("name", get_str(name)), ("filename", get_str(filename)), ("start", start), ("length", length)]
            )
            category.append(entry)

        return category
