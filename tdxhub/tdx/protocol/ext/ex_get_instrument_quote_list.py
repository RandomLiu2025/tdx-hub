import struct
from collections import OrderedDict

from tdxhub.tdx.logger import logger
from tdxhub.tdx.protocol.base import BaseParser


class GetInstrumentQuoteList(BaseParser):
    def setParams(self, market, category, start, count):
        """

        :param market:
        :param category:
        :param start:
        :param count:
        """
        pkg = bytearray.fromhex("01 c1 06 0b 00 02 0b 00 0b 00 00 24")
        pkg.extend(struct.pack("<BHHHH", market, 0, start, count, 1))

        self.category = category
        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """

        :param body_buf:
        :return:
        """
        pos = 0

        data_list = []

        (num,) = struct.unpack("<H", body_buf[pos : pos + 2])

        if num == 0:
            return []

        pos += 2

        if self.category not in [2, 3]:
            return NotImplementedError("暂时不支持期货,港股之外的品类")

        for _ in range(num):
            # 每个块一共300bytes
            market, code = struct.unpack("<B9s", body_buf[pos : pos + 10])
            code = code.strip(b"\0").decode("gbk", "ignore")  # to unicode
            pos += 10

            if self.category == 3:
                try:
                    pos = self.extract_futures(market, code, body_buf, data_list, pos)
                except Exception as e:
                    logger.exception(e)

                logger.debug(pos)

            elif self.category == 2:
                pos = self.extract_hongkong_stocks(market, code, body_buf, data_list, pos)

        return data_list

    @staticmethod
    def extract_hongkong_stocks(market, code, body_buf, datalist, pos):
        """

        :param market:
        :param code:
        :param body_buf:
        :param datalist:
        :param pos:
        :return:
        """
        data_pack_format = "<IfffffIfIIfIIIIfffffIIIIIfffffIIIII"
        (
            HuoYueDu,
            ZuoShou,
            JinKai,
            ZuiGao,
            ZuiDi,
            XianJia,
            _,  # 0
            MaiRuJia,  # ?
            ZongLiang,
            XianLiang,  # ?
            ZongJinE,
            _,  # ?
            _,  # ?
            Nei,  # 0
            Wai,  # 0 Nei/Wai = 内外比？
            MaiRuJia1,
            MaiRuJia2,
            MaiRuJia3,
            MaiRuJia4,
            MaiRuJia5,
            MaiRuLiang1,
            MaiRuLiang2,
            MaiRuLiang3,
            MaiRuLiang4,
            MaiRuLiang5,
            MaiChuJia1,
            MaiChuJia2,
            MaiChuJia3,
            MaiChuJia4,
            MaiChuJia5,
            MaiChuLiang1,
            MaiChuLiang2,
            MaiChuLiang3,
            MaiChuLiang4,
            MaiChuLiang5,
        ) = struct.unpack(data_pack_format, body_buf[pos : pos + 140])

        pos += 290

        one = OrderedDict(
            [
                ("market", market),
                ("code", code),
                ("HuoYueDu", HuoYueDu),
                ("ZuoShou", ZuoShou),
                ("JinKai", JinKai),
                ("ZuiGao", ZuiGao),
                ("ZuiDi", ZuiDi),
                ("XianJia", XianJia),
                ("MaiRuJia", MaiRuJia),
                ("ZongLiang", ZongLiang),
                ("XianLiang", XianLiang),
                ("ZongJinE", ZongJinE),
                ("Nei", Nei),
                ("Wai", Wai),  # 0 Nei/Wai = 内外比？
                ("MaiRuJia1", MaiRuJia1),
                ("MaiRuJia2", MaiRuJia2),
                ("MaiRuJia3", MaiRuJia3),
                ("MaiRuJia4", MaiRuJia4),
                ("MaiRuJia5", MaiRuJia5),
                ("MaiRuLiang1", MaiRuLiang1),
                ("MaiRuLiang2", MaiRuLiang2),
                ("MaiRuLiang3", MaiRuLiang3),
                ("MaiRuLiang4", MaiRuLiang4),
                ("MaiRuLiang5", MaiRuLiang5),
                ("MaiChuJia1", MaiChuJia1),
                ("MaiChuJia2", MaiChuJia2),
                ("MaiChuJia3", MaiChuJia3),
                ("MaiChuJia4", MaiChuJia4),
                ("MaiChuJia5", MaiChuJia5),
                ("MaiChuLiang1", MaiChuLiang1),
                ("MaiChuLiang2", MaiChuLiang2),
                ("MaiChuLiang3", MaiChuLiang3),
                ("MaiChuLiang4", MaiChuLiang4),
                ("MaiChuLiang5", MaiChuLiang5),
            ]
        )

        datalist.append(one)

        return pos

    @staticmethod
    def extract_futures(market, code, body_buf, datalist, pos):
        """

        :param market:
        :param code:
        :param body_buf:
        :param datalist:
        :param pos:
        :return:
        """

        data_pack_format = "<IfffffIIIIfIIfIfIIIIIIIIIfIIIIIIIII"

        (
            BiShu,
            ZuoJie,
            JinKai,
            ZuiGao,
            ZuiDi,
            MaiChu,
            KaiCang,
            _,
            ZongLiang,
            XianLiang,
            ZongJinE,
            NeiPan,
            WaiPan,
            _,
            ChiCangLiang,
            MaiRuJia,
            _,
            _,
            _,
            _,
            MaiRuLiang,
            _,
            _,
            _,
            _,
            MaiChuJia,
            _,
            _,
            _,
            _,
            MaiChuLiang,
            _,
            _,
            _,
            _,
        ) = struct.unpack(data_pack_format, body_buf[pos : pos + 140])

        pos += 290

        one = OrderedDict(
            [
                ("market", market),
                ("code", code),
                ("BiShu", BiShu),
                ("ZuoJie", ZuoJie),
                ("JinKai", JinKai),
                ("ZuiGao", ZuiGao),
                ("ZuiDi", ZuiDi),
                ("MaiChu", MaiChu),
                ("KaiCang", KaiCang),
                ("ZongLiang", ZongLiang),
                ("XianLiang", XianLiang),
                ("ZongJinE", ZongJinE),
                ("NeiPan", NeiPan),
                ("WaiPan", WaiPan),
                ("ChiCangLiang", ChiCangLiang),
                ("MaiRuJia", MaiRuJia),
                ("MaiRuLiang", MaiRuLiang),
                ("MaiChuJia", MaiChuJia),
                ("MaiChuLiang", MaiChuLiang),
            ]
        )

        datalist.append(one)

        return datalist
