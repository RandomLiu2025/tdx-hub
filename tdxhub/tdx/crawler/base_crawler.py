import abc
import math
import tempfile
from urllib.request import Request, urlopen

from tdxhub.tdx.errors import ProtocolError
from tdxhub.tdx.logger import logger


def fetch_report_hook(downloaded, total_size):
    logger.debug(f"Downloaded {downloaded}, Total is {total_size}")


class BaseCrawler:
    mode = "http"

    def fetch_and_parse(
        self, reporthook=None, path_to_download=None, proxies=None, chunksize=1024 * 50, *args, **kwargs
    ):
        """
        function to get data ,
        :param chunksize:
        :param args:
        :param kwargs:
        :return:
        :param reporthook 使用urllib.request 的report_hook 来汇报下载进度 \
                    参考 https://docs.python.org/3/library/urllib.request.html#module-urllib.request
        :param path_to_download 数据文件下载的地址，如果没有提供，则下载到临时文件中，并在解析之后删除
        :param proxies urllib格式的代理服务器设置
        :return: 解析之后的数据结果
        """

        method = ("get_content", "fetch_via_http")[self.mode == "http"]
        download_file = getattr(self, method)(
            reporthook=reporthook,
            path_to_download=path_to_download,
            proxies=proxies,
            chunksize=chunksize,
            *args,
            **kwargs,
        )
        try:
            return self.parse(download_file, *args, **kwargs)
        finally:
            download_file.close()

    def fetch_via_http(self, reporthook=None, path_to_download=None, chunksize=1024 * 50, *args, timeout=30, **kwargs):
        """

        :param reporthook:
        :param path_to_download:
        :param chunksize:
        :param timeout: Positive socket timeout in seconds (default 30), not a total download deadline.
        :param args:
        :param kwargs:
        :return:
        """
        if isinstance(chunksize, bool) or not isinstance(chunksize, int) or chunksize <= 0:
            raise ValueError("chunksize must be a positive integer")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a finite positive number of seconds")

        url = self.get_url(*args, **kwargs)

        request = Request(url)
        request.add_header("Referer", url)
        request.add_header(
            "User-Agent",
            r"Mozilla/5.0 (Macintosh Intel Mac OS X 10_14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/76.0.3809.100 Safari/537.36",
        )
        download_file = open(path_to_download, "w+b") if path_to_download else tempfile.NamedTemporaryFile(delete=True)
        try:
            with urlopen(request, timeout=timeout) as response:
                length_header = response.getheader("Content-Length")
                total_size = None
                if length_header is not None:
                    length_header = length_header.strip()
                    if not length_header.isascii() or not length_header.isdecimal():
                        raise ProtocolError(f"{url}: invalid Content-Length {length_header!r}")
                    try:
                        total_size = int(length_header)
                    except ValueError as exc:
                        raise ProtocolError(f"{url}: invalid Content-Length") from exc

                downloaded = 0
                while True:
                    chunk = response.read(chunksize)
                    downloaded += len(chunk)
                    if total_size is not None:
                        if downloaded > total_size:
                            raise ProtocolError(f"{url}: received {downloaded} bytes, exceeds Content-Length {total_size}")
                        if not chunk and downloaded != total_size:
                            raise ProtocolError(f"{url}: incomplete download, received {downloaded} of {total_size} bytes")
                    if chunk:
                        download_file.write(chunk)
                    if reporthook:
                        reporthook(downloaded, total_size if total_size is not None else 0)
                    if not chunk:
                        break

            download_file.seek(0)
            return download_file
        except BaseException:
            download_file.close()
            raise

    @abc.abstractmethod
    def get_url(self, *args, **kwargs):
        """

        :param args:
        :param kwargs:
        """
        raise NotImplementedError("will impl in subclass")

    @abc.abstractmethod
    def get_content(self, reporthook=None, path_to_download=None, proxies=None, chunksize=1024 * 50, *args, **kwargs):
        """

        :param reporthook:
        :param path_to_download:
        :param proxies:
        :param chunksize:
        :param args:
        :param kwargs:
        """
        raise NotImplementedError("will impl in subclass")

    @abc.abstractmethod
    def parse(self, download_file, *args, **kwargs):
        """

        :param download_file:
        :param args:
        :param kwargs:
        """
        raise NotImplementedError("will impl in subclass")
