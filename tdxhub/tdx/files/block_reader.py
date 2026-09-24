import struct
from collections import OrderedDict
from pathlib import Path

import pandas as pd

from tdxhub.tdx.files.base_reader import BaseReader

"""
参考这个 http://blog.csdn.net/Metal1/article/details/44352639
"""

BlockReader_TYPE_FLAT = 0
BlockReader_TYPE_GROUP = 1


class BlockReader(BaseReader):
    def get_df(self, name, result_type=BlockReader_TYPE_FLAT):
        """
        转换 pd.DataFrame
        :param name:
        :param result_type:
        :return:
        """

        result = self.get_data(name, result_type)

        return pd.DataFrame(result)

    @staticmethod
    def get_data(name, result_type=BlockReader_TYPE_FLAT):
        """
        解析数据
        :param name:
        :param result_type:
        :return:
        """
        result = []

        data = (type(name) is bytearray) and name or Path(name).read_bytes()

        pos = 384

        (num,) = struct.unpack("<H", data[pos : pos + 2])

        pos += 2

        for i in range(num):
            block_name_raw = data[pos : pos + 9]

            pos += 9

            block_name = block_name_raw.decode("gbk", "ignore").rstrip("\x00")
            stock_count, block_type = struct.unpack("<HH", data[pos : pos + 4])

            pos += 4

            block_stock_begin = pos
            codes = []

            for code_index in range(stock_count):
                one_code = data[pos : pos + 7].decode("utf-8", "ignore").rstrip("\x00")

                pos += 7

                if result_type == BlockReader_TYPE_FLAT:
                    result.append(
                        OrderedDict(
                            [
                                ("blockname", block_name),  # noqa
                                ("block_type", block_type),
                                ("code_index", code_index),
                                ("code", one_code),
                            ]
                        )
                    )
                elif result_type == BlockReader_TYPE_GROUP:
                    codes.append(one_code)

            if result_type == BlockReader_TYPE_GROUP:
                result.append(
                    OrderedDict(
                        [
                            ("blockname", block_name),
                            ("block_type", block_type),
                            ("stock_count", stock_count),
                            ("code_list", ",".join(codes)),
                        ]
                    )
                )  # noqa

            pos = block_stock_begin + 2800

        return result


class CustomerBlockReader(BaseReader):
    """
    读取通达信备份的自定义板块文件夹，返回格式与通达信板块一致，在广发证券客户端上测试通过，其它未测试
    """

    def get_df(self, name, result_type=BlockReader_TYPE_FLAT):
        """
        转换 pd.DataFrame
        :param name:
        :param result_type:
        :return:
        """
        result = self.get_data(name, result_type)
        return pd.DataFrame(result)

    @staticmethod
    def get_data(name, result_type=BlockReader_TYPE_FLAT):
        """
        解析数据
        :param name:
        :param result_type:
        :return:
        """
        if not Path(name).is_dir():
            raise Exception("not a directory")

        block_file = "/".join([name, "blocknew.cfg"])  # noqa

        if not Path(block_file).exists():
            raise Exception("file not exists")

        block_data = open(block_file, "rb").read()

        pos = 0
        result = []

        while pos < len(block_data):
            n1 = block_data[pos : pos + 50].decode("gbk", "ignore").rstrip("\x00")
            n2 = block_data[pos + 50 : pos + 120].decode("gbk", "ignore").rstrip("\x00")

            pos = pos + 120

            n1 = n1.split("\x00")[0]
            n2 = n2.split("\x00")[0]
            bf = "/".join([name, n2 + ".blk"])

            if not Path(bf).exists():
                raise Exception("file not exists")

            codes = open(bf).read().splitlines()

            if result_type == BlockReader_TYPE_FLAT:
                for index, code in enumerate(codes):
                    code and result.append(
                        OrderedDict([("blockname", n1), ("block_type", n2), ("code_index", index), ("code", code[1:])])
                    )  # noqa

            if result_type == BlockReader_TYPE_GROUP:
                cc = [c[1:] for c in codes if c != ""]
                result.append(
                    OrderedDict(
                        [("blockname", n1), ("block_type", n2), ("stock_count", len(cc)), ("code_list", ",".join(cc))]
                    )
                )  # noqa

        return result
