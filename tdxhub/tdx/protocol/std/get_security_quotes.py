import struct
from collections import OrderedDict

from tdxhub.tdx.codec import get_price, get_security_coefficient, get_volume
from tdxhub.tdx.protocol.base import BaseParser


class GetSecurityQuotesCmd(BaseParser):
    def setParams(self, all_stock):
        """
        :param all_stock: 一个包含 (market, code) 元组的列表， 如 [ (0, '000001'), (1, '600001') ]
        :return:
        """
        stock_len = len(all_stock)

        if stock_len <= 0:
            return False

        pkgdatalen = stock_len * 7 + 12

        val = (0x10C, 0x02006320, pkgdatalen, pkgdatalen, 0x5053E, 0, 0, stock_len)
        pkg = bytearray(struct.pack("<HIHHIIHH", *val))

        for stock in all_stock:
            market, code = stock

            if type(code) is str:
                code = code.encode("utf-8")

            one_stock_pkg = struct.pack("<B6s", market, code)
            pkg.extend(one_stock_pkg)

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """

        :param body_buf:
        :return:
        """
        pos = 0
        pos += 2  # skip b1 cb

        (num_stock,) = struct.unpack("<H", body_buf[pos : pos + 2])

        pos += 2
        stocks = []

        for _ in range(num_stock):
            # print(body_buf[pos:])
            # b'\x00000001\x95\n\x87\x0e\x01\x01\x05\x00\xb1\xb9\xd6\r\xc7\x0e\x8d\xd7\x1a\x84\x04S\x9c<M\xb6\xc8\x0e\x97\x8e\x0c\x00\xae\n\x00\x01\xa0\x1e\x9e\xb3\x03A\x02\x84\xf9\x01\xa8|B\x03\x8c\xd6\x01\xb0lC\x04\xb7\xdb\x02\xac\x7fD\x05\xbb\xb0\x01\xbe\xa0\x01y\x08\x01GC\x04\x00\x00\x95\n'
            market, code, active1 = struct.unpack("<B6sH", body_buf[pos : pos + 9])
            pos += 9

            price, pos = get_price(body_buf, pos)  # noqa
            last_close_diff, pos = get_price(body_buf, pos)

            open_diff, pos = get_price(body_buf, pos)
            high_diff, pos = get_price(body_buf, pos)
            low_diff, pos = get_price(body_buf, pos)

            reversed_bytes0, pos = get_price(body_buf, pos)
            reversed_bytes1, pos = get_price(body_buf, pos)

            vol, pos = get_price(body_buf, pos)
            cur_vol, pos = get_price(body_buf, pos)

            (amount_raw,) = struct.unpack("<I", body_buf[pos : pos + 4])
            amount = get_volume(amount_raw)
            pos += 4

            s_vol, pos = get_price(body_buf, pos)  # noqa
            b_vol, pos = get_price(body_buf, pos)

            reversed_bytes2, pos = get_price(body_buf, pos)
            reversed_bytes3, pos = get_price(body_buf, pos)

            bid1, pos = get_price(body_buf, pos)
            ask1, pos = get_price(body_buf, pos)

            bid_vol1, pos = get_price(body_buf, pos)
            ask_vol1, pos = get_price(body_buf, pos)

            bid2, pos = get_price(body_buf, pos)
            ask2, pos = get_price(body_buf, pos)

            bid_vol2, pos = get_price(body_buf, pos)
            ask_vol2, pos = get_price(body_buf, pos)

            bid3, pos = get_price(body_buf, pos)  # noqa
            ask3, pos = get_price(body_buf, pos)

            bid_vol3, pos = get_price(body_buf, pos)
            ask_vol3, pos = get_price(body_buf, pos)

            bid4, pos = get_price(body_buf, pos)
            ask4, pos = get_price(body_buf, pos)

            bid_vol4, pos = get_price(body_buf, pos)
            ask_vol4, pos = get_price(body_buf, pos)

            bid5, pos = get_price(body_buf, pos)
            ask5, pos = get_price(body_buf, pos)

            bid_vol5, pos = get_price(body_buf, pos)
            ask_vol5, pos = get_price(body_buf, pos)

            reversed_bytes4 = struct.unpack("<H", body_buf[pos : pos + 2])
            pos += 2

            reversed_bytes5, pos = get_price(body_buf, pos)
            reversed_bytes6, pos = get_price(body_buf, pos)

            reversed_bytes7, pos = get_price(body_buf, pos)
            reversed_bytes8, pos = get_price(body_buf, pos)

            reversed_bytes9, active2 = struct.unpack("<hH", body_buf[pos : pos + 4])
            pos += 4

            code = code.decode("utf-8")
            coefficient = get_security_coefficient(market, code)

            one_stock = OrderedDict(
                [
                    ("market", market),
                    ("code", code),
                    ("active1", active1),
                    ("price", self._cal_price(price, 0, coefficient)),
                    ("last_close", self._cal_price(price, last_close_diff, coefficient)),
                    ("open", self._cal_price(price, open_diff, coefficient)),
                    ("high", self._cal_price(price, high_diff, coefficient)),
                    ("low", self._cal_price(price, low_diff, coefficient)),
                    ("servertime", self._format_time("%s" % reversed_bytes0)),
                    ("reversed_bytes0", reversed_bytes0),
                    ("reversed_bytes1", reversed_bytes1),
                    ("vol", vol),
                    ("cur_vol", cur_vol),
                    ("amount", amount),
                    ("s_vol", s_vol),
                    ("b_vol", b_vol),
                    ("reversed_bytes2", reversed_bytes2),
                    ("reversed_bytes3", reversed_bytes3),
                    ("bid1", self._cal_price(price, bid1, coefficient)),
                    ("ask1", self._cal_price(price, ask1, coefficient)),
                    ("bid_vol1", bid_vol1),
                    ("ask_vol1", ask_vol1),
                    ("bid2", self._cal_price(price, bid2, coefficient)),
                    ("ask2", self._cal_price(price, ask2, coefficient)),
                    ("bid_vol2", bid_vol2),
                    ("ask_vol2", ask_vol2),
                    ("bid3", self._cal_price(price, bid3, coefficient)),
                    ("ask3", self._cal_price(price, ask3, coefficient)),
                    ("bid_vol3", bid_vol3),
                    ("ask_vol3", ask_vol3),
                    ("bid4", self._cal_price(price, bid4, coefficient)),
                    ("ask4", self._cal_price(price, ask4, coefficient)),
                    ("bid_vol4", bid_vol4),
                    ("ask_vol4", ask_vol4),
                    ("bid5", self._cal_price(price, bid5, coefficient)),
                    ("ask5", self._cal_price(price, ask5, coefficient)),
                    ("bid_vol5", bid_vol5),
                    ("ask_vol5", ask_vol5),
                    ("reversed_bytes4", reversed_bytes4),
                    ("reversed_bytes5", reversed_bytes5),
                    ("reversed_bytes6", reversed_bytes6),
                    ("reversed_bytes7", reversed_bytes7),
                    ("reversed_bytes8", reversed_bytes8),
                    ("reversed_bytes9", reversed_bytes9 / 100.0),  # 涨速
                    ("active2", active2),
                ]
            )

            stocks.append(one_stock)

        return stocks

    @staticmethod
    def _cal_price(base_p, diff, coefficient=0.01):
        """

        :param base_p:
        :param diff:
        :return:
        """
        return float(base_p + diff) * coefficient

    @staticmethod
    def _format_time(time_stamp):
        """
        format time from reversed_bytes0
        by using method from https://github.com/rainx/pytdx/issues/187
        :param time_stamp:
        :return:
        """
        if not int(time_stamp):
            return time_stamp

        time = time_stamp[:8][:-6] + ":"

        if int(time_stamp[-6:-4]) < 60:
            time += "%s:" % time_stamp[-6:-4]
            time += "%06.3f" % (int(time_stamp[-4:]) * 60 / 10000.0)
        else:
            time += "%02d:" % (int(time_stamp[-6:]) * 60 / 1000000)
            time += "%06.3f" % ((int(time_stamp[-6:]) * 60 % 1000000) * 60 / 1000000.0)

        return time
