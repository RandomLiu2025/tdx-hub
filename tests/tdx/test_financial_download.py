"""Offline download integrity and financial crawler regression tests."""

import hashlib
import io
import struct
import zipfile
from types import MappingProxyType
from unittest.mock import Mock

import pytest

from tdxhub.affair import fetch_file
from tdxhub.financial.base import BaseFinancial
from tdxhub.financial.financial import FinancialList
from tdxhub.tdx.client import StandardClient
from tdxhub.tdx.crawler import base_crawler
from tdxhub.tdx.crawler.history_financial_crawler import HistoryFinancialCrawler, HistoryFinancialListCrawler
from tdxhub.tdx.errors import ProtocolError, ValidationException
from tdxhub.tdx.files import HistoryFinancialReader


def chunk(data):
    return {"chunksize": len(data), "chunkdata": data}


@pytest.mark.parametrize("filesize", [0, 6])
def test_download_assembles_chunks_without_padding_and_reports_progress(filesize):
    client = StandardClient()
    client.get_report_file = Mock(side_effect=[chunk(b"abc"), chunk(b"def"), {"chunksize": 0}])
    progress = Mock()

    result = client.get_report_file_by_size("tdxfin/demo.dat", filesize, progress)

    assert isinstance(result, bytearray)
    assert result == b"abcdef"
    assert [call.args[1] for call in client.get_report_file.call_args_list] == ([0, 3, 6] if not filesize else [0, 3])
    assert [call.args for call in progress.call_args_list] == [(3, filesize), (6, filesize)]


def test_unknown_length_empty_file():
    client = StandardClient()
    client.get_report_file = Mock(return_value={"chunksize": 0})
    assert client.get_report_file_by_size("empty.dat") == bytearray()
    client.get_report_file.assert_called_once_with("empty.dat", 0)


def test_known_length_retries_empty_chunks_and_resets_after_progress():
    client = StandardClient()
    empty = {"chunksize": 0}
    client.get_report_file = Mock(side_effect=[empty, empty, chunk(b"abc"), empty, empty, chunk(b"def")])
    assert client.get_report_file_by_size("demo.dat", 6) == b"abcdef"
    assert [call.args[1] for call in client.get_report_file.call_args_list] == [0, 0, 0, 3, 3, 3]


def test_known_length_rejects_truncated_download_after_three_empty_chunks():
    client = StandardClient()
    client.get_report_file = Mock(side_effect=[chunk(b"abc"), *[{"chunksize": 0}] * 3])
    with pytest.raises(ProtocolError, match="demo.dat"):
        client.get_report_file_by_size("demo.dat", 6)
    assert client.get_report_file.call_count == 4


@pytest.mark.parametrize("filesize", [0, 6])
@pytest.mark.parametrize(
    "response",
    [
        None,
        {"chunksize": 3, "chunkdata": b"ab"},
        {"chunksize": 2, "chunkdata": b"abc"},
        {"chunksize": 0, "chunkdata": b"abc"},
        {"chunksize": -1, "chunkdata": b""},
    ],
)
def test_download_rejects_failed_or_inconsistent_chunks(filesize, response):
    client = StandardClient()
    client.get_report_file = Mock(side_effect=[response, {"chunksize": 0}])
    with pytest.raises(ProtocolError, match="demo.dat"):
        client.get_report_file_by_size("demo.dat", filesize)
    client.get_report_file.assert_called_once_with("demo.dat", 0)


def test_download_rejects_total_larger_than_manifest():
    client = StandardClient()
    client.get_report_file = Mock(return_value=chunk(b"abcd"))
    with pytest.raises(ProtocolError, match="demo.dat"):
        client.get_report_file_by_size("demo.dat", 3)


@pytest.fixture
def financial_data():
    header = struct.pack("<hIH3L", 1, 20260920, 1, 0, 4, 0)
    index = struct.pack("<6scL", b"600000", b"\0", len(header) + struct.calcsize("<6scL"))
    dat = header + index + struct.pack("<f", 1.5)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("gpcw20260920.dat", dat)
    return dat, output.getvalue()


@pytest.fixture
def fake_server(monkeypatch):
    def install(payload):
        calls = []

        def get_report_file(self, filename, offset):
            calls.append((filename, offset))
            return chunk(payload[offset : offset + 11])

        monkeypatch.setattr(StandardClient, "connect", lambda self, *args, **kwargs: self)
        monkeypatch.setattr(StandardClient, "get_report_file", get_report_file)
        monkeypatch.setattr(BaseFinancial, "__init__", lambda self: setattr(self, "bestip", ("127.0.0.1", 7709)))
        return calls

    return install


def test_manifest_download_passes_md5_and_skips_verified_file(tmp_path, financial_data, fake_server):
    _, payload = financial_data
    calls = fake_server(payload)
    entry = {"filename": "gpcw20260920.zip", "filesize": len(payload), "hash": hashlib.md5(payload).hexdigest()}
    path = fetch_file(tmp_path, entry)
    assert path.read_bytes() == payload
    calls.clear()
    assert fetch_file(tmp_path, entry) == path
    assert calls == []


@pytest.mark.parametrize("zipped", [False, True])
@pytest.mark.parametrize("destination", [None, "download.bin"])
def test_content_crawler_parses_default_and_explicit_downloads(
    zipped,
    destination,
    tmp_path,
    financial_data,
    fake_server,
):
    payload = financial_data[int(zipped)]
    fake_server(payload)
    path = tmp_path / destination if destination else None
    rows = HistoryFinancialCrawler().fetch_and_parse(
        filename="gpcw20260920.zip" if zipped else "gpcw20260920.dat",
        filesize=len(payload),
        path_to_download=path,
    )
    assert rows == [("600000", 20260920, 1.5)]
    if path:
        assert path.read_bytes() == payload


def test_list_crawler_parses_explicit_path(tmp_path, fake_server):
    payload = b"gpcw20260920.zip,md5,42\n"
    fake_server(payload)
    path = tmp_path / "gpcw.txt"
    assert HistoryFinancialListCrawler().fetch_and_parse(path_to_download=path) == [
        {"filename": "gpcw20260920.zip", "hash": "md5", "filesize": 42},
    ]
    assert path.read_bytes() == payload


def test_public_financial_list_parses_explicit_path(tmp_path, fake_server):
    fake_server(b"gpcw20260920.zip,md5,42\n")
    assert FinancialList().fetch_and_parse(downdir=tmp_path / "gpcw.txt") == [
        {"filename": "gpcw20260920.zip", "hash": "md5", "filesize": 42},
    ]


@pytest.mark.parametrize("with_length", [False, True])
@pytest.mark.parametrize("destination", [None, "download.bin"])
def test_http_crawler_parses_zip_and_closes_response(
    with_length,
    destination,
    monkeypatch,
    tmp_path,
    financial_data,
):
    payload = financial_data[1]
    response = io.BytesIO(payload)
    response.getheader = lambda name: str(len(payload)) if with_length else None
    monkeypatch.setattr(base_crawler, "urlopen", lambda request, **kwargs: response)
    crawler = HistoryFinancialCrawler()
    crawler.mode = "http"
    path = tmp_path / destination if destination else None
    assert crawler.fetch_and_parse(filename="gpcw20260920.zip", path_to_download=path, chunksize=11) == [
        ("600000", 20260920, 1.5),
    ]
    assert response.closed
    if path:
        assert path.read_bytes() == payload


def test_download_stream_is_closed_when_parsing_fails(monkeypatch):
    stream = io.BytesIO(b"broken")
    crawler = HistoryFinancialListCrawler()
    monkeypatch.setattr(crawler, "get_content", lambda **kwargs: stream)
    with pytest.raises(IndexError):
        crawler.fetch_and_parse()
    assert stream.closed


@pytest.mark.parametrize("failure", ["connect", "read"])
def test_http_failure_closes_download_and_response(monkeypatch, failure):
    download = io.BytesIO()
    response = io.BytesIO()
    response.getheader = lambda name: "10"
    response.read = Mock(side_effect=OSError("read failed"))
    monkeypatch.setattr(base_crawler.tempfile, "NamedTemporaryFile", lambda **kwargs: download)
    monkeypatch.setattr(
        base_crawler,
        "urlopen",
        Mock(side_effect=OSError("connect failed")) if failure == "connect" else Mock(return_value=response),
    )
    with pytest.raises(OSError, match=f"{failure} failed"):
        HistoryFinancialCrawler().fetch_via_http(filename="report.zip")
    assert download.closed
    if failure == "read":
        assert response.closed


@pytest.mark.parametrize("zipped", [False, True])
def test_parser_rewinds_and_keeps_callers_stream_open(zipped, financial_data):
    with io.BytesIO(financial_data[int(zipped)]) as stream:
        stream.seek(3)
        assert HistoryFinancialCrawler().parse(stream) == [("600000", 20260920, 1.5)]
        assert not stream.closed


def test_corrupt_zip_is_not_parsed_as_dat():
    with io.BytesIO(b"broken") as stream:
        stream.name = "report.ZIP"
        with pytest.raises(zipfile.BadZipFile):
            HistoryFinancialCrawler().parse(stream)
        assert not stream.closed


def test_zip_ignores_directories_and_accepts_nested_uppercase_dat(financial_data):
    with io.BytesIO() as stream:
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("reports.dat/", b"")
            archive.writestr("reports.dat/report.DAT", financial_data[0])
        assert HistoryFinancialCrawler().parse(stream) == [("600000", 20260920, 1.5)]


@pytest.mark.parametrize("names", [[], ["first.dat", "second.dat"]])
def test_zip_requires_one_dat_member(names, financial_data):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name in names:
            archive.writestr(name, financial_data[0])
    stream.seek(0)
    with pytest.raises(ValidationException, match="dat"):
        HistoryFinancialCrawler().parse(stream)
    assert not stream.closed


def test_reader_still_reads_zip_and_keeps_dat_schema(tmp_path, financial_data):
    for suffix, payload in zip(("dat", "zip"), financial_data, strict=True):
        path = tmp_path / f"gpcw20260920.{suffix}"
        path.write_bytes(payload)
        frame = HistoryFinancialReader().get_df(path)
        assert frame.loc["600000", "col001"] == 1.5
        assert frame.loc["600000", "report_date"] == 20260920


@pytest.mark.parametrize("filesize", [-1, 1.5, "3", None, True, False, float("nan"), float("inf")])
def test_download_rejects_invalid_filesize_before_request(filesize):
    client = StandardClient()
    client.get_report_file = Mock(return_value={"chunksize": 0})
    with pytest.raises(ValueError, match="filesize"):
        client.get_report_file_by_size("demo.dat", filesize)
    client.get_report_file.assert_not_called()


@pytest.mark.parametrize("offset", [0, 3])
@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        b"bad",
        "bad",
        1,
        {},
        {"chunksize": None},
        {"chunksize": "1", "chunkdata": b"a"},
        {"chunksize": True, "chunkdata": b"a"},
        {"chunksize": False},
        {"chunksize": 1.0, "chunkdata": b"a"},
        {"chunksize": 1, "chunkdata": None},
        {"chunksize": 1, "chunkdata": 1},
        {"chunksize": 1, "chunkdata": "a"},
        {"chunksize": 1, "chunkdata": [97]},
        {"chunksize": 0, "chunkdata": None},
        {"chunksize": 0, "chunkdata": []},
    ],
)
def test_download_rejects_malformed_responses_with_offset(response, offset):
    client = StandardClient()
    responses = [chunk(b"abc")] if offset else []
    client.get_report_file = Mock(side_effect=[*responses, response, {"chunksize": 0}])
    with pytest.raises(ProtocolError, match=rf"demo\.dat: .*offset {offset}"):
        client.get_report_file_by_size("demo.dat")
    assert client.get_report_file.call_count == len(responses) + 1


def test_download_accepts_bytearray_chunks_and_propagates_callback_errors():
    client = StandardClient()
    client.get_report_file = Mock(return_value=chunk(bytearray(b"abc")))
    assert client.get_report_file_by_size("demo.dat", 3) == b"abc"
    error = TypeError("callback failed")
    with pytest.raises(TypeError) as exc:
        client.get_report_file_by_size("demo.dat", 3, Mock(side_effect=error))
    assert exc.value is error


def test_download_accepts_readonly_mapping():
    client = StandardClient()
    client.get_report_file = Mock(return_value=MappingProxyType(chunk(b"abc")))
    assert client.get_report_file_by_size("demo.dat", 3) == b"abc"


@pytest.fixture
def http_response(monkeypatch):
    def install(payload=b"abc", length=None):
        response = io.BytesIO(payload)
        response.getheader = Mock(return_value=length)
        response.read = Mock(wraps=response.read)
        opener = Mock(return_value=response)
        monkeypatch.setattr(base_crawler, "urlopen", opener)
        return response, opener

    return install


@pytest.mark.parametrize("length", [None, "6", " 6 "])
def test_http_reads_bounded_chunks_and_reports_progress(length, http_response):
    response, opener = http_response(b"abcdef", length)
    progress = Mock()
    with HistoryFinancialCrawler().fetch_via_http(filename="demo.dat", chunksize=2, reporthook=progress) as stream:
        assert stream.read() == b"abcdef"
    assert response.closed
    assert [call.args for call in response.read.call_args_list] == [(2,)] * 4
    total = 0 if length is None else 6
    assert [call.args for call in progress.call_args_list] == [(2, total), (4, total), (6, total), (6, total)]
    assert opener.call_args.kwargs == {"timeout": 30}


@pytest.mark.parametrize("length", [None, "0"])
def test_http_accepts_empty_body(length, http_response):
    response, _ = http_response(b"", length)
    progress = Mock()
    with HistoryFinancialCrawler().fetch_via_http(filename="empty.dat", reporthook=progress) as stream:
        assert stream.read() == b""
    assert response.closed
    progress.assert_called_once_with(0, 0)


@pytest.mark.parametrize("length", [None, "3"])
def test_http_continues_after_short_nonempty_reads(length, http_response):
    response, _ = http_response(b"", length)
    response.read.side_effect = [b"a", b"bc", b""]
    with HistoryFinancialCrawler().fetch_via_http(filename="demo.dat", chunksize=5) as stream:
        assert stream.read() == b"abc"
    assert [call.args for call in response.read.call_args_list] == [(5,)] * 3
    assert response.closed


def test_http_does_not_parse_or_report_completion_for_truncated_body(http_response):
    response, _ = http_response(b"abc", "4")
    crawler = HistoryFinancialCrawler()
    crawler.mode = "http"
    crawler.parse = Mock()
    progress = Mock()
    with pytest.raises(ProtocolError, match="received 3 of 4"):
        crawler.fetch_and_parse(filename="demo.dat", reporthook=progress)
    assert response.closed
    progress.assert_called_once_with(3, 4)
    crawler.parse.assert_not_called()


@pytest.mark.parametrize("length", ["10", "2", "0", "-1", "abc", "", "1.5", "+3", "３", "3, 3"])
def test_http_rejects_invalid_lengths_and_closes_streams(length, monkeypatch, http_response):
    response, _ = http_response(b"abc", length)
    download = io.BytesIO()
    monkeypatch.setattr(base_crawler.tempfile, "NamedTemporaryFile", lambda **kwargs: download)
    with pytest.raises(ProtocolError, match="demo.dat"):
        HistoryFinancialCrawler().fetch_via_http(filename="demo.dat", chunksize=2)
    assert download.closed
    assert response.closed


@pytest.mark.parametrize("parameter", ["chunksize", "timeout"])
@pytest.mark.parametrize("value", [0, -1, "2", None, True, False, float("nan"), float("inf"), float("-inf")])
def test_http_rejects_invalid_parameters_before_io(parameter, value, tmp_path, monkeypatch):
    path = tmp_path / "existing.dat"
    path.write_bytes(b"preserve")
    opener = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(base_crawler, "urlopen", opener)
    with pytest.raises(ValueError, match=parameter):
        HistoryFinancialCrawler().fetch_via_http(filename="demo.dat", path_to_download=path, **{parameter: value})
    assert path.read_bytes() == b"preserve"
    opener.assert_not_called()


def test_http_rejects_fractional_chunksize_before_io(monkeypatch):
    opener = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(base_crawler, "urlopen", opener)
    with pytest.raises(ValueError, match="chunksize"):
        HistoryFinancialCrawler().fetch_via_http(filename="demo.dat", chunksize=1.5)
    opener.assert_not_called()


@pytest.mark.parametrize("timeout", [1, 0.25])
def test_http_forwards_custom_timeout_through_fetch_and_parse(timeout, financial_data, http_response):
    response, opener = http_response(financial_data[1])
    crawler = HistoryFinancialCrawler()
    crawler.mode = "http"
    assert crawler.fetch_and_parse(filename="demo.zip", timeout=timeout) == [("600000", 20260920, 1.5)]
    assert opener.call_args.kwargs == {"timeout": timeout}
    assert response.closed


@pytest.mark.parametrize("failure", ["connect", "read", "callback"])
def test_http_timeout_and_callback_errors_close_streams(failure, monkeypatch, http_response):
    response, opener = http_response(b"abc", "3")
    download = io.BytesIO()
    monkeypatch.setattr(base_crawler.tempfile, "NamedTemporaryFile", lambda **kwargs: download)
    error = TypeError("callback failed") if failure == "callback" else TimeoutError("timed out")
    progress = Mock()
    if failure == "connect":
        opener.side_effect = error
    elif failure == "read":
        response.read.side_effect = error
    else:
        progress.side_effect = error
    with pytest.raises(type(error)) as exc:
        HistoryFinancialCrawler().fetch_via_http(filename="demo.dat", timeout=0.1, reporthook=progress)
    assert exc.value is error
    assert download.closed
    if failure != "connect":
        assert response.closed
