import struct
from datetime import datetime

from tdxhub.tdx.constants import SECURITY_COEFFICIENT
from tdxhub.tdx.logger import logger


def get_price(data, pos):
    """
    分析了一下，貌似是类似utf-8的编码方式保存有符号数字

    :param data:
    :param pos:
    :return:
    """

    pos_byte = 6

    bdata = index_bytes(data, pos)
    int_data = bdata & 0x3F

    if bdata & 0x40:
        sign = True
    else:
        sign = False

    if bdata & 0x80:
        while True:
            pos += 1

            bdata = index_bytes(data, pos)

            int_data += (bdata & 0x7F) << pos_byte
            pos_byte += 7

            if bdata & 0x80:
                pass
            else:
                break

    pos += 1

    if sign:
        int_data = -int_data

    return int_data, pos


def get_volume(vol):
    """Decode the little-endian IEEE-754 float32 turnover/volume field.

    The upstream hand-expanded formula mishandles zero and some exponent /
    mantissa boundaries (for example 0x3f800000, which encodes 1.0).
    Decode the wire bits directly; do not round small nonzero values to zero.
    """
    return struct.unpack("<f", struct.pack("<I", vol))[0]


def get_datetime(category, buffer, pos):
    """
    获取日期时间
    :param category:
    :param buffer:
    :param pos:
    :return:
    """
    minute = 0
    hour = 15

    if category < 4 or category == 7 or category == 8:
        zip_day, minutes = struct.unpack("<HH", buffer[pos : pos + 4])

        month = int((zip_day % 2048) / 100)
        year = (zip_day >> 11) + 2004
        day = (zip_day % 2048) % 100

        minute = minutes % 60
        hour = int(minutes / 60)
    else:
        (zip_day,) = struct.unpack("<I", buffer[pos : pos + 4])

        month = int((zip_day % 10000) / 100)
        year = int(zip_day / 10000)
        day = zip_day % 100

    pos += 4

    return year, month, day, hour, minute, pos


def get_time(buffer, pos):
    """
    获取时间
    :param buffer:
    :param pos:
    :return:
    """
    (minutes,) = struct.unpack("<H", buffer[pos : pos + 2])

    hour = int(minutes / 60)
    minute = minutes % 60

    pos += 2

    return hour, minute, pos


def index_bytes(data, pos):
    """
    索引比特
    :param data:
    :param pos:
    :return:
    """
    return data[pos]


# def get_security_coefficient(market, name):
#     return SECURITY_COEFFICIENT[get_security_type(market, name)]


# TODO 增加 get_coefficient 函数
def get_security_coefficient(market=None, code=None):
    try:
        security_type = get_security_type(market=market, code=code)
        coefficient = SECURITY_COEFFICIENT[security_type]
        return coefficient[0]
    except NotImplementedError:
        logger.error("NotImplementedError")
        return 0.01


def get_transaction_coefficient(market, code):
    """Tick prices use three decimals for bonds, unlike quote snapshots."""
    if isinstance(code, bytes):
        code = code.decode("ascii")
    try:
        if get_security_type(market, code).endswith("_BOND"):
            return 0.001
    except NotImplementedError:
        pass
    return get_security_coefficient(market, code)


def get_security_type(market, code):
    """
    获取股票类型, A股, B股, 指数等

    :param market: 市场
    :param code: 代码
    :return:
    """

    # code = Path(code).stem
    code = str(code)
    code_head = str(code)[:2]

    if market in ["SZ", "sz", 0]:
        if code_head in ["00", "30"]:
            return "SZ_A_STOCK"

        if code_head in ["20"]:
            return "SZ_B_STOCK"

        if code_head in ["39"]:
            return "SZ_INDEX"

        if code_head in ["15", "16", "18"]:
            return "SZ_FUND"

        if code_head in ["10", "11", "12", "13", "14"]:
            return "SZ_BOND"

    if market in ["SH", "sh", 1]:
        if code_head in ["60", "68"]:  # 688XXX科创板
            return "SH_A_STOCK"

        if code_head in ["90"]:
            return "SH_B_STOCK"

        if code_head in ["00", "88", "99"]:
            return "SH_INDEX"

        if code_head in ["50", "51", "52", "56", "58"]:
            return "SH_FUND"

        if code_head in ["01", "10", "11", "12", "13", "14", "20"]:
            return "SH_BOND"

    if market in ["BJ", "bj", 2] and len(code) == 6 and code.isascii() and code.isdigit():
        if code_head == "89":
            return "BJ_INDEX"
        if code.startswith("920") or (code.startswith(("4", "8")) and code_head != "89"):
            return "BJ_A_STOCK"

    logger.debug("Unknown security exchange !")
    raise NotImplementedError


def dump(buf):
    from pprint import pprint

    try:
        from hexdump import hexdump

        pprint(hexdump(buf))
    except ImportError:
        pprint(buf)


def time_frame(current_time=None):
    """
    判断时间是否在交易时间段内
    :param current_time: 要检查的时间, 如果空则默认当前时间
    :return: 在交易时间段内返回 True， 否则返回 False
    """
    current_time = current_time or datetime.now()

    start_time = datetime.strptime(str(current_time.date()) + "9:30", "%Y-%m-%d%H:%M")
    end_time = datetime.strptime(str(current_time.date()) + "11:30", "%Y-%m-%d%H:%M")

    if start_time < current_time < end_time:
        return True

    start_time = datetime.strptime(str(current_time.date()) + "13:00", "%Y-%m-%d%H:%M")
    end_time = datetime.strptime(str(current_time.date()) + "15:00", "%Y-%m-%d%H:%M")

    if start_time < current_time < end_time:
        return True

    return False
