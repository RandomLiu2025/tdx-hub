import struct

from tdxhub.tdx.protocol.base import BaseParser


class GetReportFile(BaseParser):
    def setParams(self, filename, offset=0):
        """
        设置参数
        :param filename: 文件名
        :param offset: 获取数量
        """
        pkg = bytearray.fromhex("0C 12 34 00 00 00")

        # Fom DTGear request.py file
        node_size = 0x7530

        raw_data = struct.pack(r"<H2I100s", 0x06B9, offset, node_size, filename.encode("utf-8"))
        raw_data_len = struct.calcsize(r"<H2I100s")

        pkg.extend(struct.pack(f"<HH{raw_data_len}s", raw_data_len, raw_data_len, raw_data))

        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        """

        :param body_buf:
        :return:
        """

        (chunk_size,) = struct.unpack("<I", body_buf[:4])

        if chunk_size > 0:
            return {"chunksize": chunk_size, "chunkdata": body_buf[4:]}

        return {"chunksize": 0}
