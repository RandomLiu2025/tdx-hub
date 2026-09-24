import io
import tempfile
import zipfile

import pandas as pd

from ..errors import ValidationException
from ..financial_data import parse_financial_dat, unique_financial_records
from ..financial_path import validate_financial_filename
from .base_crawler import BaseCrawler

class HistoryFinancialListCrawler(BaseCrawler):
    """
    获取历史财务数据的接口，参考上面issue里面 @datochan 的方案和代码
        https://github.com/rainx/tdxpy/issues/133
    """

    mode = "content"

    def get_url(self, *args, **kwargs):
        """

        :param args:
        :param kwargs:
        :return:
        """
        return "https://gitee.com/yutiansut/QADATA/raw/master/financial/content.txt"

    def get_content(self, reporthook=None, path_to_download=None, proxies=None, chunksize=1024 * 50, *args, **kwargs):
        """

        :param reporthook:
        :param path_to_download:
        :param proxies:
        :param chunksize:
        :param args:
        :param kwargs:
        :return:
        """
        from tdxhub.tdx.client import StandardClient

        api = StandardClient()
        api.need_setup = False

        # calc.tdx.com.cn, calc2.tdx.com.cn
        with api.connect(ip="120.76.152.87"):
            content = api.get_report_file_by_size("tdxfin/gpcw.txt")
            download_file = (
                open(path_to_download, "w+b") if path_to_download else tempfile.NamedTemporaryFile(delete=True)
            )
            download_file.write(content)
            download_file.seek(0)

            return download_file

    def parse(self, download_file, *args, **kwargs):
        """

        :param download_file:
        :param args:
        :param kwargs:
        :return:
        """
        content = download_file.read()
        content = content.decode("utf-8")

        def list_to_dict(li):
            return {"filename": li[0], "hash": li[1], "filesize": int(li[2])}

        result = [list_to_dict(x) for x in [line.strip().split(",") for line in content.strip().split("\n")]]

        return result


class HistoryFinancialCrawler(BaseCrawler):
    mode = "content"

    def get_url(self, *args, **kwargs):
        """

        :param args:
        :param kwargs:
        :return:
        """
        if "filename" not in kwargs:
            raise ValidationException("Param filename is not set")

        filename = validate_financial_filename(kwargs["filename"])

        return f"http://data.yutiansut.com/{filename}"  # noqa

    def get_content(self, reporthook=None, path_to_download=None, proxies=None, chunksize=1024 * 50, *args, **kwargs):
        """

        :param reporthook:
        :param path_to_download:
        :param proxies:
        :param chunksize:
        :param args:
        :param kwargs:
        :return:
        """
        from tdxhub.tdx.client import StandardClient

        if "filename" not in kwargs:
            raise ValidationException("Param filename is not set")

        filename = validate_financial_filename(kwargs["filename"])
        file_size = kwargs.get("filesize", 0)

        api = StandardClient()
        api.need_setup = False

        with api.connect(ip="120.76.152.87"):
            # calc.tdx.com.cn, calc2.tdx.com.cn
            content = api.get_report_file_by_size(f"tdxfin/{filename}", filesize=file_size, reporthook=reporthook)
            download_file = (
                open(path_to_download, "w+b") if path_to_download else tempfile.NamedTemporaryFile(delete=True)
            )
            download_file.write(content)
            download_file.seek(0)

            return download_file

    def parse(self, download_file, *args, **kwargs):
        """

        :param download_file:
        :param args:
        :param kwargs:
        :return:
        """
        download_file.seek(0)
        if zipfile.is_zipfile(download_file) or str(getattr(download_file, "name", "")).lower().endswith(".zip"):
            with zipfile.ZipFile(download_file) as archive:
                members = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".dat")]
                if len(members) != 1:
                    raise ValidationException(f"expected one dat file in zip archive, found {len(members)}")
                with io.BytesIO(archive.read(members[0])) as dat_file:
                    return self._parse_dat(dat_file)

        download_file.seek(0)
        return self._parse_dat(download_file)

    @staticmethod
    def _parse_dat(dat_file):
        return parse_financial_dat(dat_file.read())

    @staticmethod
    def to_df(data):
        if not data:
            return None

        data = unique_financial_records(data)
        col = ["code", "report_date"]
        col += [f"col{str(i).zfill(3)}" for i in range(1, len(data[0]) - 1)]

        df = pd.DataFrame(data=data, columns=col)
        df.set_index("code", inplace=True)

        return df
