from tdxhub.tdx.crawler.history_financial_crawler import HistoryFinancialCrawler
from tdxhub.tdx.files.base_reader import BaseReader


class HistoryFinancialReader(BaseReader):
    """
    使用 history_financial_cralwer 里面的HistoryFinancialCrawler完成此功能，这个reader仅对其做简单的封装
    """

    def get_df(self, data_file, **kwargs):
        """
        读取历史财务数据文件，并返回pandas结果 ， 类似gpcw20171231.zip格式，具体字段含义参考

        https://github.com/rainx/tdxpy/issues/133

        :param data_file: 数据文件地址， 数据文件类型可以为 .zip 文件，也可以为解压后的 .dat
        :return: pandas DataFrame格式的历史财务数据
        """

        crawler = HistoryFinancialCrawler()

        with open(data_file, "rb") as df:
            data = crawler.parse(download_file=df)

        return crawler.to_df(data)
