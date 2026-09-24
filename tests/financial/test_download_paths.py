"""Offline regression tests for untrusted financial download filenames."""

import hashlib
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from tdxhub.affair import Affair, download, fetch_file
from tdxhub.financial.financial import Financial
from tdxhub.tdx.client import StandardClient
from tdxhub.tdx.crawler.history_financial_crawler import HistoryFinancialCrawler
from tdxhub.tdx.financial_path import financial_download_path, validate_financial_filename

BAD_NAMES = [
    "../escaped.dat", "sub/../../escaped.dat", "/tmp/escaped.dat",
    r"..\escaped.dat", r"C:\escaped.dat", "C:escaped.dat", r"\\server\share\escaped.dat",
    "sub/report.zip", r"sub\report.zip", "", ".", "..", "file\x00.dat", "file\n.dat",
    "file.dat:stream", "file.dat ", "file.dat.", "NUL", "CON.dat", "LPT1.zip", None,
]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(Financial, "__init__", lambda self: setattr(self, "bestip", ("offline", 7709)))
    monkeypatch.setattr(StandardClient, "connect", lambda self, *args, **kwargs: self)
    result = Mock(return_value=b"downloaded content")
    monkeypatch.setattr(StandardClient, "get_report_file_by_size", result)
    return result


@pytest.mark.parametrize("name", BAD_NAMES)
@pytest.mark.parametrize("entry", ["content", "manifest", "download", "crawler", "url"])
def test_rejects_unsafe_names_before_io(tmp_path, server, name, entry):
    dest = tmp_path / "reports"
    with pytest.raises(ValueError):
        if entry == "content":
            Financial().content(downdir=dest, filename=name)
        elif entry == "manifest":
            fetch_file(dest, {"filename": name})
        elif entry == "download":
            download(dest, name)
        elif entry == "crawler":
            HistoryFinancialCrawler().get_content(filename=name)
        else:
            HistoryFinancialCrawler().get_url(filename=name)
    server.assert_not_called()
    assert not dest.exists()


@pytest.mark.parametrize("name", [name for name in BAD_NAMES if name is not None])
@pytest.mark.parametrize("method", [Affair.fetch, Affair.parse])
def test_public_entry_rejects_names_before_download(tmp_path, monkeypatch, name, method):
    fetch = Mock(side_effect=AssertionError("unexpected download"))
    monkeypatch.setattr(Financial, "fetch_only", fetch)
    with pytest.raises(ValueError):
        method(downdir=tmp_path / "reports", filename=name)
    fetch.assert_not_called()
    assert not (tmp_path / "reports").exists()


def test_bulk_validates_entire_manifest_before_starting_workers(tmp_path, monkeypatch, server):
    monkeypatch.setattr(Affair, "files", lambda: [
        {"filename": "valid.zip", "filesize": 1, "hash": "0" * 32}, {"filename": "../bad.zip"},
    ])
    with pytest.raises(ValueError, match="非法财务文件名"):
        Affair.fetch(tmp_path / "reports")
    server.assert_not_called()
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("entry", ["content", "manifest", "fetch", "parse", "download"])
def test_rejects_existing_or_dangling_symlinks(tmp_path, server, existing, entry):
    dest = tmp_path / "reports"
    dest.mkdir()
    outside = tmp_path / "outside.zip"
    if existing:
        outside.write_bytes(b"must not touch")
    (dest / "report.zip").symlink_to(outside)
    manifest = {"filename": "report.zip", "hash": hashlib.md5(b"must not touch").hexdigest()}
    with pytest.raises(ValueError, match="符号链接"):
        if entry == "content":
            Financial().content(downdir=dest, filename="report.zip")
        elif entry == "manifest":
            fetch_file(dest, manifest)
        elif entry == "download":
            download(dest, "report.zip")
        else:
            getattr(Affair, entry)(dest, "report.zip")
    server.assert_not_called()
    assert outside.read_bytes() == b"must not touch" if existing else not outside.exists()


def test_hard_link_is_replaced_not_truncated(tmp_path, server):
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"original")
    dest = tmp_path / "reports"
    dest.mkdir()
    target = dest / "report.zip"
    os.link(outside, target)
    Financial().fetch_only(downdir=dest, filename=target.name)
    assert outside.read_bytes() == b"original"
    assert target.read_bytes() == b"downloaded content"
    assert not target.samefile(outside)
    assert sorted(path.name for path in dest.iterdir()) == [target.name]


def test_rechecks_symlink_created_during_download(tmp_path, server):
    dest = tmp_path / "reports"
    dest.mkdir()
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"original")

    def add_symlink(*args, **kwargs):
        (dest / "report.zip").symlink_to(outside)
        return b"downloaded content"

    server.side_effect = add_symlink
    with pytest.raises(ValueError, match="符号链接"):
        Financial().fetch_only(downdir=dest, filename="report.zip")
    assert outside.read_bytes() == b"original"
    assert not list(dest.glob(".tdxhub-*"))


def test_replace_failure_preserves_previous_file_and_cleans_staging(tmp_path, server, monkeypatch):
    target = tmp_path / "report.zip"
    target.write_bytes(b"original")
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        Financial().fetch_only(downdir=tmp_path, filename=target.name)
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".tdxhub-*"))


@pytest.mark.parametrize("name", ["gpcw20260630.zip", "gpcw20260630.DAT", "财务.dat", "a..b.zip"])
def test_normal_basenames_still_work(tmp_path, server, name):
    assert validate_financial_filename(name) == name
    dest = tmp_path / "new" / "reports"
    with Financial().content(downdir=dest, filename=name) as stream:
        assert stream.read() == b"downloaded content"
    assert (dest / name).read_bytes() == b"downloaded content"
    assert server.call_args.args == (f"tdxfin/{name}",)


def test_caller_selected_directory_alias_and_relative_return(tmp_path, monkeypatch, server):
    dest = tmp_path / "reports"
    dest.mkdir()
    (tmp_path / "alias").symlink_to(dest, target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    assert financial_download_path("alias", "report.zip") == Path("alias/report.zip")
    monkeypatch.setattr(Affair, "files", lambda: [{
        "filename": "report.zip", "filesize": len(b"downloaded content"),
        "hash": hashlib.md5(b"downloaded content").hexdigest(),
    }])
    assert Affair.fetch("alias", "report.zip") == Path("alias/report.zip")
    assert (dest / "report.zip").read_bytes() == b"downloaded content"


@pytest.mark.parametrize("target_type", ["directory", "fifo"])
def test_rejects_non_regular_target_before_download(tmp_path, server, target_type):
    target = tmp_path / "report.zip"
    if target_type == "directory":
        target.mkdir()
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO is unavailable on this platform")
        os.mkfifo(target)
    with pytest.raises(ValueError, match="不是普通文件"):
        Financial().content(downdir=tmp_path, filename=target.name)
    server.assert_not_called()
    assert target.exists()
    assert not list(tmp_path.glob(".tdxhub-*"))
