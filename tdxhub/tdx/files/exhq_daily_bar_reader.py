import struct
from pathlib import Path

import pandas as pd

from tdxhub.tdx.files.base_reader import BaseReader, TdxFileNotFoundException


class TdxExHqDailyBarReader(BaseReader):
    """
    读取通达信数据
    """

    def parse_data_by_file(self, filename):
        """
        按文件名解析内容
        :param filename:
        :return:
        """
        if not Path(filename).is_file():
            raise TdxFileNotFoundException(f"no tdx kline data, please check path {filename}")

        content = Path(filename).read_bytes()
        content = self.unpack_records("<IffffIIf", content)  # noqa

        return content

    def get_df(self, code_or_file, **kwargs):
        """
        转换 pd.DataFrame 格式
        :param code_or_file:
        :param kwargs:
        :return:
        """
        columns = ["date", "open", "high", "low", "close", "amount", "volume", "jiesuan", "hk_stock_amount"]  # noqa
        data = [self._df_convert(row) for row in self.parse_data_by_file(code_or_file)]

        df = pd.DataFrame(data=data, columns=columns)
        df.index = pd.to_datetime(df.date)
        df = df[["open", "high", "low", "close", "amount", "volume", "jiesuan", "hk_stock_amount"]]  # noqa

        return df

    @staticmethod
    def _df_convert(row):
        """

        :param row:
        :return:
        """
        t_date = str(row[0])
        datestr = t_date[:4] + "-" + t_date[4:6] + "-" + t_date[6:]

        (hk_stock_amount,) = struct.unpack("<f", struct.pack("<I", row[5]))
        new_row = (datestr, row[1], row[2], row[3], row[4], row[5], row[6], row[7], hk_stock_amount)

        return new_row
