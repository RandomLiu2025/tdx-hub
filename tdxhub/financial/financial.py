import tempfile
import zipfile
from pathlib import Path

import pandas as pd

from tdxhub.tdx.client import StandardClient
from tdxhub.tdx.financial_data import parse_financial_dat, unique_financial_records
from tdxhub.tdx.financial_integrity import validate_financial_metadata, verify_financial_stream
from tdxhub.tdx.financial_path import (
    financial_download_path,
    validate_financial_filename,
    write_financial_download,
)

from ..logger import logger
from .base import BaseFinancial
from .columns import columns


class FinancialReader(object):
    @staticmethod
    def to_data(filename, **kwargs):
        """
        读取历史财务数据文件，并返回pandas结果 ， 类似 `gpcw20171231.zip` 格式，具体字段含义参考

        https://github.com/rainx/pytdx/issues/133

        :param filename: 数据文件地址， 数据文件类型可以为 .zip 文件，也可以为解压后的 .dat, 可以不写扩展名. 程序自动识别
        :return: pandas DataFrame 格式的历史财务数据
        """

        crawler = Financial()

        with open(filename, 'rb') as fp:
            data = crawler.parse(download_file=fp)

        return crawler.to_df(data, **kwargs)


class FinancialList(BaseFinancial):
    def content(self, report_hook=None, downdir=None, proxies=None, chunk_size=1024 * 50, *args, **kwargs):
        """
        解析财务文件

        :param report_hook: 钩子回调函数
        :param downdir: 要解析的文件夹
        :param proxies:
        :param chunk_size:
        :param args:
        :param kwargs:
        :return:
        """

        api = StandardClient(**kwargs)
        api.need_setup = False

        with api.connect(*self.bestip):
            content = api.get_report_file_by_size('tdxfin/gpcw.txt')
            download_file = open(downdir, 'w+b') if downdir else tempfile.NamedTemporaryFile(delete=True)
            download_file.write(content)
            download_file.seek(0)

            return download_file

    def parse(self, download_file, *args, **kwargs):
        """
        解析财务文件

        :param download_file:
        :param args:
        :param kwargs:
        :return:
        """

        with download_file:
            content = download_file.read()
            content = content.decode('utf-8')

        def l2d(i):
            return {'filename': i[0], 'hash': i[1], 'filesize': int(i[2])}

        if content:
            content = content.strip().split('\n')
            return [l2d(i) for i in [line.strip().split(',') for line in content]]

        return None


class Financial(BaseFinancial):
    def content(self, report_hook=None, downdir=None, proxies=None, chunk_size=51200, *args, **kwargs):
        """
        解析财务文件

        :param report_hook: 钩子回调函数
        :param downdir: 要解析的文件夹
        :param proxies: 代理配置
        :param chunk_size:
        :param args:
        :param kwargs:
        :return:
        """

        # Low-level callers may supply their own manifest snapshot. Affair's
        # public downloads always supply both length and MD5.
        filename = validate_financial_filename(kwargs.get('filename'))
        if downdir is not None:
            financial_download_path(downdir, filename)
        filesize, expected_md5 = validate_financial_metadata(
            kwargs.get('filesize', 0), kwargs.get('expected_md5'),
        )

        logger.debug(f'{filename}: start download...')

        api = StandardClient()
        api.need_setup = False

        with api.connect(*self.bestip):
            content = api.get_report_file_by_size(f'tdxfin/{filename}', filesize=filesize, reporthook=report_hook)
            if downdir is not None:
                download_file = write_financial_download(
                    downdir, filename, content, filesize=filesize, expected_md5=expected_md5,
                )
            else:
                download_file = tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=True)
                try:
                    download_file.write(content)
                    download_file.flush()
                    verify_financial_stream(download_file, filename=filename, filesize=filesize, expected_md5=expected_md5)
                    download_file.seek(0)
                except BaseException:
                    download_file.close()
                    raise

            del content

            logger.debug(f'{filename}: done')

            return download_file

    def parse(self, download_file, *args, **kwargs):
        """
        解析财务文件

        :param download_file: 要解析的文件
        :param args:
        :param kwargs:
        :return:
        """

        suffix = Path(download_file.name).suffix.lower()
        try:
            if suffix == '.zip':
                with zipfile.ZipFile(download_file) as archive:
                    members = [
                        item for item in archive.infolist()
                        if not item.is_dir() and item.filename.lower().endswith('.dat')
                    ]
                    if len(members) != 1:
                        raise ValueError(f'财务压缩包应包含一个 .dat 文件，实际为 {len(members)} 个')
                    payload = archive.read(members[0])
            elif suffix == '.dat':
                download_file.seek(0)
                payload = download_file.read()
            else:
                raise ValueError(f'不支持的财务文件格式: {suffix}')
        finally:
            download_file.close()

        return parse_financial_dat(payload)

    @staticmethod
    def to_df(data, header='zh'):
        """
        转换数据为 pandas DataFrame 格式

        :param data: 要转换的数据
        :param header: 'zh' 为唯一中文表头，'en' 保留 colN / FINVALUE 编号
        :return: DataFrame
        """

        if len(data) == 0 or len(data[0]) == 0:
            return pd.DataFrame(data=None)

        data = unique_financial_records(data)
        column = ['code', 'report_date']

        for i in range(1, len(data[0]) - 1):
            column.append('col' + str(i))

        df = pd.DataFrame(data=data, columns=column).set_index('code')

        if header == 'zh':
            labels = list(columns)
            if len(labels) < len(df.columns):
                labels.extend(df.columns[len(labels):])
            df.columns = labels[:len(df.columns)]
            if not df.columns.is_unique:
                raise ValueError("财务中文表头存在重名，请使用 header='en' 保留 FINVALUE 编号")

        logger.debug(df.shape)

        return df
