import struct

from tdxhub.tdx import logger
from tdxhub.tdx.files.block_reader import BlockReader, BlockReader_TYPE_FLAT
from tdxhub.tdx.protocol.base import BaseParser


class GetBlockInfoMeta(BaseParser):
    def setParams(self, block_file):
        """
        设置参数
        :param block_file:
        """
        if type(block_file) is str:
            block_file = block_file.encode("utf-8")

        pkg = bytearray.fromhex("0C 39 18 69 00 01 2A 00 2A 00 C5 02")
        pkg.extend(struct.pack(f"<{0x2A - 2}s", block_file))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """
        解析结果
        :param body_buf:
        :return:
        """
        size, _, hash_value, _ = struct.unpack("<I1s32s1s", body_buf)

        return {"size": size, "hash_value": hash_value}


class GetBlockInfo(BaseParser):
    def setParams(self, block_file, start, size):
        """
        设置参数
        :param block_file: 板块文件名
        :param start: 开始位置
        :param size: 容量
        """
        if type(block_file) is str:
            block_file = block_file.encode("utf-8")

        pkg = bytearray.fromhex("0c 37 18 6a 00 01 6e 00 6e 00 b9 06")
        pkg.extend(struct.pack(f"<II{0x6E - 10}s", start, size, block_file))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """
        解析结果
        :param body_buf:
        :return:
        """
        return body_buf[4:]


def get_and_parse_block_info(client, block_file):
    """
    获取价格和板块信息
    :param client: 客户端
    :param block_file: 板块文件名
    :return:
    """
    try:
        meta = client.get_block_info_meta(block_file)

        if not meta:
            return None
    except Exception as exc:
        logger.logger.exception(exc)
        return None

    size = meta["size"]
    one_chunk = 0x7530

    chunks = size // one_chunk

    if size % one_chunk != 0:
        chunks += 1

    file_content = bytearray()

    for seg in range(chunks):
        piece_data = client.get_block_info(block_file, seg * one_chunk, size)
        file_content.extend(piece_data)

    content = BlockReader().get_data(file_content, BlockReader_TYPE_FLAT)

    return content
