import struct
from collections import OrderedDict

from tdxhub.tdx.protocol.base import BaseParser


class GetInstrumentQuote(BaseParser):
    def setParams(self, market, code):
        """

        :param market:
        :param code:
        """
        pkg = bytearray.fromhex("01 01 08 02 02 01 0c 00 0c 00 fa 23")
        pkg.extend(struct.pack("<B9s", market, code.encode("utf-8")))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """

        :param body_buf:
        :return:
        """
        if len(body_buf) < 20:
            return []

        pos = 0

        market, code = struct.unpack("<B9s", body_buf[pos : pos + 10])

        pos += 10
        pos += 4

        # 持仓 ((13340,), 66),
        (
            pre_close,
            open_price,
            high,
            low,
            price,
            kaicang,
            _,
            zongliang,
            xianliang,
            _,
            neipan,
            waipai,
            _,
            chicang,
            b1,
            b2,
            b3,
            b4,
            b5,
            bv1,
            bv2,
            bv3,
            bv4,
            bv5,
            a1,
            a2,
            a3,
            a4,
            a5,
            av1,
            av2,
            av3,
            av4,
            av5,
        ) = struct.unpack("<fffffIIIIIIIIIfffffIIIIIfffffIIIII", body_buf[pos : pos + 136])

        return [
            OrderedDict(
                [
                    ("market", market),
                    ("code", code.decode("utf-8").rstrip("\x00")),
                    ("pre_close", pre_close),
                    ("open", open_price),
                    ("high", high),
                    ("low", low),
                    ("price", price),
                    ("kaicang", kaicang),
                    ("zongliang", zongliang),
                    ("xianliang", xianliang),
                    ("neipan", neipan),
                    ("waipan", waipai),
                    ("chicang", chicang),
                    ("bid1", b1),
                    ("bid2", b2),
                    ("bid3", b3),
                    ("bid4", b4),
                    ("bid5", b5),
                    ("bid_vol1", bv1),
                    ("bid_vol2", bv2),
                    ("bid_vol3", bv3),
                    ("bid_vol4", bv4),
                    ("bid_vol5", bv5),
                    ("ask1", a1),
                    ("ask2", a2),
                    ("ask3", a3),
                    ("ask4", a4),
                    ("ask5", a5),
                    ("ask_vol1", av1),
                    ("ask_vol2", av2),
                    ("ask_vol3", av3),
                    ("ask_vol4", av4),
                    ("ask_vol5", av5),
                ]
            )
        ]
