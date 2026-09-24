"""Decode the standard-server financial summary (0x0010), in yuan and shares."""

import math
import struct
from collections import OrderedDict

from tdxhub.tdx.errors import ProtocolError
from tdxhub.tdx.protocol.base import BaseParser

# Names describe the legacy wire slots, not necessarily their current meaning.
FINANCE_FIELDS = (
    "liutongguben",
    "province",
    "industry",
    "updated_date",
    "ipo_date",
    "zongguben",
    "guojiagu",
    "faqirenfarengu",
    "farengu",
    "bgu",
    "hgu",
    "zhigonggu",
    "zongzichan",
    "liudongzichan",
    "gudingzichan",
    "wuxingzichan",
    "gudongrenshu",
    "liudongfuzhai",
    "changqifuzhai",
    "zibengongjijin",
    "jingzichan",
    "zhuyingshouru",
    "zhuyinglirun",
    "yingshouzhangkuan",
    "yingyelirun",
    "touzishouyu",
    "jingyingxianjinliu",
    "zongxianjinliu",
    "cunhuo",
    "lirunzonghe",
    "shuihoulirun",
    "jinglirun",
    "weifenpeilirun",
    "meigujingzichan",
    "baoliu2",
)
FINANCE_STRUCT = struct.Struct("<fHHII30f")
SHARE_FIELDS = ("liutongguben", "zongguben", "bgu", "hgu")
AMOUNT_FIELDS = (
    "zongzichan",
    "liudongzichan",
    "gudingzichan",
    "wuxingzichan",
    "liudongfuzhai",
    "zibengongjijin",
    "jingzichan",
    "zhuyingshouru",
    "yingshouzhangkuan",
    "yingyelirun",
    "touzishouyu",
    "jingyingxianjinliu",
    "zongxianjinliu",
    "cunhuo",
    "lirunzonghe",
    "shuihoulirun",
    "jinglirun",
    "weifenpeilirun",
)
# Four recorded SH/SZ/BJ securities match current and prior-year FINVALUE data.
RENAMED_FIELDS = {
    "faqirenfarengu": ("shangniantongqijinglirun", 1000),
    "farengu": ("shangniantongqiyingyeshouru", 1000),
    "zhigonggu": ("meigushouyi", 1),
    "changqifuzhai": ("shaoshugudongquanyi", 1000),
    "zhuyinglirun": ("yingyechengben", 1000),
}


class GetFinanceInfo(BaseParser):
    def setParams(self, market, code):
        if isinstance(code, str):
            code = code.encode("ascii")
        self._security = (market, bytes(code))
        pkg = bytearray.fromhex("0c 1f 18 76 00 01 0b 00 0b 00 10 00 01 00")
        pkg.extend(struct.pack("<B6s", market, code))
        self.send_pkg = pkg

    def parseResponse(self, body_buf):
        if len(body_buf) < 2:
            raise ProtocolError("finance response missing record count")
        (count,) = struct.unpack_from("<H", body_buf)
        if count == 0 and len(body_buf) == 2:
            return OrderedDict()
        expected_size = 2 + 7 + FINANCE_STRUCT.size
        if count != 1 or len(body_buf) != expected_size:
            raise ProtocolError(f"finance response invalid count/length: count={count}, bytes={len(body_buf)}")
        market, code = struct.unpack_from("<B6s", body_buf, 2)
        if market not in (0, 1, 2) or not code.isdigit():
            raise ProtocolError("finance response invalid market/code")
        if hasattr(self, "_security") and (market, code) != self._security:
            raise ProtocolError("finance response market/code does not match request")
        values = FINANCE_STRUCT.unpack_from(body_buf, 9)
        if not all(math.isfinite(value) for value in values):
            raise ProtocolError("finance response contains non-finite numeric value")
        raw = dict(zip(FINANCE_FIELDS, values, strict=True))
        result = OrderedDict(market=market, code=code.decode("ascii"))
        result.update(raw)
        for name in SHARE_FIELDS:
            result[name] = raw[name] * 10000  # ten thousand shares -> shares
        for name in AMOUNT_FIELDS:
            result[name] = raw[name] * 1000  # thousand yuan -> yuan (not *10000)
        # Unknown slot: do not claim it is state-owned shares.
        result["guojiagu"] = None
        for old, (name, scale) in RENAMED_FIELDS.items():
            result[old] = None
            result[name] = raw[old] * scale
        result["finance_schema"] = "tdx_finance_v2"
        result["raw_fields"] = raw
        return result
