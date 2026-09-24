"""Manifest validation and verify-before-publish regressions; no live network."""

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from tdxhub.affair import Affair, download, fetch_file
from tdxhub.financial.base import BaseFinancial
from tdxhub.financial.financial import Financial
from tdxhub.tdx.client import StandardClient
from tdxhub.tdx.financial_path import write_financial_download

PAYLOAD = b"verified financial payload"


def metadata(filename="report.zip", payload=PAYLOAD):
    return {"filename": filename, "filesize": len(payload), "hash": hashlib.md5(payload).hexdigest()}


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(BaseFinancial, "__init__", lambda self: setattr(self, "bestip", ("offline", 7709)))
    monkeypatch.setattr(StandardClient, "connect", lambda self, *args, **kwargs: self)
    content = Mock(return_value=PAYLOAD)
    manifest = Mock(return_value=[metadata()])
    monkeypatch.setattr(StandardClient, "get_report_file_by_size", content)
    monkeypatch.setattr(Affair, "files", manifest)
    return content, manifest


def invoke(entry, dest):
    if entry == "single":
        return Affair.fetch(dest, "report.zip")
    if entry == "batch":
        return Affair.fetch(dest)[0]
    if entry == "download":
        assert download(dest, "report.zip") is True
        return dest / "report.zip"
    return fetch_file(dest, metadata())


@pytest.mark.parametrize("entry", ["single", "batch", "download", "manifest"])
def test_all_entries_verify_and_reuse_valid_cache(tmp_path, remote, entry):
    content, manifest = remote
    path = invoke(entry, tmp_path)
    assert path == tmp_path / "report.zip"
    assert path.read_bytes() == PAYLOAD
    assert invoke(entry, tmp_path) == path
    content.assert_called_once()
    assert content.call_args.kwargs["filesize"] == len(PAYLOAD)
    assert manifest.call_count == (0 if entry == "manifest" else 2)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.zip"]


@pytest.mark.parametrize("entry", ["single", "batch", "download", "manifest"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("bad", [b"short", PAYLOAD + b"extra", b"x" * len(PAYLOAD)])
def test_bad_download_never_publishes_or_deletes_old_file(tmp_path, remote, entry, existing, bad):
    content, _ = remote
    content.return_value = bad
    target = tmp_path / "report.zip"
    if existing:
        target.write_bytes(b"old copy")
    with pytest.raises(OSError, match="校验失败"):
        invoke(entry, tmp_path)
    assert target.read_bytes() == b"old copy" if existing else not target.exists()
    assert not list(tmp_path.glob(".tdxhub-*"))


@pytest.mark.parametrize("entry", ["single", "batch", "manifest"])
def test_network_failure_keeps_old_copy(tmp_path, remote, entry):
    content, _ = remote
    content.side_effect = OSError("network interrupted")
    target = tmp_path / "report.zip"
    target.write_bytes(b"old copy")
    with pytest.raises(OSError, match="network interrupted"):
        invoke(entry, tmp_path)
    assert target.read_bytes() == b"old copy"
    assert not list(tmp_path.glob(".tdxhub-*"))


@pytest.mark.parametrize("cached", [b"short", b"x" * len(PAYLOAD)])
def test_bad_cache_is_replaced_only_after_valid_download(tmp_path, remote, cached):
    content, _ = remote
    target = tmp_path / "report.zip"
    target.write_bytes(cached)
    fetch_file(tmp_path, metadata())
    assert target.read_bytes() == PAYLOAD
    content.assert_called_once()


def test_cache_must_match_length_even_if_md5_matches(tmp_path, remote):
    content, manifest = remote
    target = tmp_path / "report.zip"
    target.write_bytes(PAYLOAD)
    manifest.return_value[0]["filesize"] += 1
    with pytest.raises(OSError, match="长度校验失败"):
        Affair.fetch(tmp_path, target.name)
    content.assert_called_once()
    assert target.read_bytes() == PAYLOAD


def test_uppercase_hash_accepted_for_cache(tmp_path, remote):
    content, manifest = remote
    target = tmp_path / "report.zip"
    target.write_bytes(PAYLOAD)
    manifest.return_value[0]["hash"] = metadata()["hash"].upper()
    assert Affair.fetch(tmp_path, target.name) == target
    content.assert_not_called()


@pytest.mark.parametrize("field,bad", [
    ("filesize", None), ("filesize", 0), ("filesize", -1), ("filesize", True),
    ("filesize", "25"), ("filesize", 25.0), ("hash", None), ("hash", ""),
    ("hash", "g" * 32), ("hash", "a" * 31), ("hash", "a" * 33), ("hash", 12),
])
@pytest.mark.parametrize("entry", ["single", "batch", "manifest"])
def test_malformed_manifest_fails_before_io(tmp_path, remote, field, bad, entry):
    content, manifest = remote
    item = metadata()
    item[field] = bad
    manifest.return_value = [metadata("other.zip"), item]
    dest = tmp_path / "absent"
    with pytest.raises(ValueError):
        if entry == "manifest":
            fetch_file(dest, item)
        else:
            invoke(entry, dest)
    content.assert_not_called()
    assert not dest.exists()


@pytest.mark.parametrize("field", ["filesize", "hash"])
def test_missing_manifest_metadata_does_not_fall_back(tmp_path, remote, field):
    content, manifest = remote
    del manifest.return_value[0][field]
    with pytest.raises(ValueError):
        Affair.fetch(tmp_path / "absent", "report.zip")
    content.assert_not_called()
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("with_cache", [False, True])
@pytest.mark.parametrize("failure", ["missing", "unavailable"])
def test_no_unchecked_fallback_when_manifest_missing_or_unavailable(tmp_path, remote, with_cache, failure):
    content, manifest = remote
    target = tmp_path / "report.zip"
    if with_cache:
        target.write_bytes(PAYLOAD)
    if failure == "missing":
        manifest.return_value = []
    else:
        manifest.side_effect = OSError("manifest unavailable")
    with pytest.raises(OSError):
        Affair.fetch(tmp_path, target.name)
    content.assert_not_called()
    assert target.read_bytes() == PAYLOAD if with_cache else not target.exists()


def test_identical_manifest_duplicates_download_once(tmp_path, remote):
    content, manifest = remote
    manifest.return_value = [metadata(), metadata()]
    manifest.return_value[1]["hash"] = metadata()["hash"].upper()
    assert Affair.fetch(tmp_path) == [tmp_path / "report.zip"]
    content.assert_called_once()


@pytest.mark.parametrize("change", [{"hash": "0" * 32}, {"filesize": 1}, {"filename": "REPORT.ZIP"}])
def test_conflicting_duplicates_abort_before_any_download(tmp_path, remote, change):
    content, manifest = remote
    manifest.return_value = [metadata(), {**metadata(), **change}]
    with pytest.raises(ValueError, match="冲突"):
        Affair.fetch(tmp_path / "absent")
    content.assert_not_called()
    assert not (tmp_path / "absent").exists()


def test_unicode_aliases_do_not_race_to_same_destination(tmp_path, remote):
    content, manifest = remote
    manifest.return_value = [metadata("caf\u00e9.zip"), metadata("cafe\u0301.zip")]
    with pytest.raises(ValueError, match="冲突"):
        Affair.fetch(tmp_path)
    content.assert_not_called()


def test_empty_manifest_still_returns_empty_batch(tmp_path, remote):
    content, manifest = remote
    manifest.return_value = []
    assert Affair.fetch(tmp_path / "absent") == []
    content.assert_not_called()
    assert not (tmp_path / "absent").exists()


def test_verified_staging_is_checked_before_replace(tmp_path, monkeypatch):
    target = tmp_path / "report.zip"
    target.write_bytes(b"old copy")
    replace = Path.replace

    def observe(staged, dest):
        assert target.read_bytes() == b"old copy"
        assert staged.read_bytes() == PAYLOAD
        return replace(staged, dest)

    observed = Mock(side_effect=observe)
    monkeypatch.setattr(Path, "replace", lambda source, dest: observed(source, dest))
    with write_financial_download(tmp_path, target.name, PAYLOAD,
                                  filesize=len(PAYLOAD), expected_md5=metadata()["hash"]) as stream:
        assert stream.read() == PAYLOAD
    observed.assert_called_once()
    observed.reset_mock()
    with pytest.raises(OSError, match="MD5 校验失败"):
        write_financial_download(tmp_path, target.name, b"x" * len(PAYLOAD),
                                 filesize=len(PAYLOAD), expected_md5=metadata()["hash"])
    observed.assert_not_called()
    assert target.read_bytes() == PAYLOAD
    assert not list(tmp_path.glob(".tdxhub-*"))


@pytest.mark.parametrize("bad_field,bad_value", [("filesize", False), ("filesize", ""),
                                                ("filesize", -1), ("expected_md5", "bad")])
def test_low_level_rejects_bad_metadata_before_network(tmp_path, remote, bad_field, bad_value):
    content, _ = remote
    with pytest.raises(ValueError):
        Financial().content(downdir=tmp_path / "absent", filename="report.zip", **{bad_field: bad_value})
    content.assert_not_called()
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("valid", [True, False])
def test_temporary_download_is_verified_and_closed_on_failure(tmp_path, remote, monkeypatch, valid):
    from tdxhub.financial import financial

    content, _ = remote
    if not valid:
        content.return_value = b"x" * len(PAYLOAD)
    opened = []
    original = financial.tempfile.NamedTemporaryFile

    def create(**kwargs):
        stream = original(dir=tmp_path, **kwargs)
        opened.append(stream)
        return stream

    monkeypatch.setattr(financial.tempfile, "NamedTemporaryFile", create)
    if valid:
        with Financial().content(filename="report.zip", filesize=len(PAYLOAD),
                                 expected_md5=metadata()["hash"]) as stream:
            assert stream.read() == PAYLOAD
    else:
        with pytest.raises(OSError, match="MD5 校验失败"):
            Financial().content(filename="report.zip", filesize=len(PAYLOAD), expected_md5=metadata()["hash"])
    assert len(opened) == 1 and opened[0].closed
    assert not list(tmp_path.iterdir())


def test_staged_file_corruption_is_caught_before_publish(tmp_path, monkeypatch):
    from tdxhub.tdx import financial_path

    target = tmp_path / "report.zip"
    target.write_bytes(b"old copy")
    verify = financial_path.verify_financial_file

    def corrupt_then_verify(staged, **kwargs):
        staged.write_bytes(b"x" * len(PAYLOAD))
        return verify(staged, **kwargs)

    monkeypatch.setattr(financial_path, "verify_financial_file", corrupt_then_verify)
    replace = Mock(side_effect=AssertionError("bad file must not be published"))
    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(OSError, match="MD5 校验失败"):
        write_financial_download(tmp_path, target.name, PAYLOAD,
                                 filesize=len(PAYLOAD), expected_md5=metadata()["hash"])
    replace.assert_not_called()
    assert target.read_bytes() == b"old copy"
    assert not list(tmp_path.glob(".tdxhub-*"))


def test_single_file_fetch_reads_real_manifest_and_downloads_matching_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(BaseFinancial, "__init__", lambda self: setattr(self, "bestip", ("offline", 7709)))
    monkeypatch.setattr(StandardClient, "connect", lambda self, *args, **kwargs: self)
    row = metadata()
    manifest = f"report.zip,{row['hash']},{row['filesize']}\n".encode()
    paths = []

    def chunk(self, filename, offset):
        paths.append(filename)
        payload = {"tdxfin/gpcw.txt": manifest, "tdxfin/report.zip": PAYLOAD}[filename]
        data = payload[offset:offset + 11]
        return {"chunksize": len(data), "chunkdata": data}

    monkeypatch.setattr(StandardClient, "get_report_file", chunk)
    target = Affair.fetch(tmp_path, "report.zip")
    assert target.read_bytes() == PAYLOAD
    assert set(paths) == {"tdxfin/gpcw.txt", "tdxfin/report.zip"}
    paths.clear()
    assert Affair.fetch(tmp_path, "report.zip") == target
    assert set(paths) == {"tdxfin/gpcw.txt"}


def test_existing_local_parse_does_not_require_manifest(tmp_path, remote, monkeypatch):
    from tdxhub.financial.financial import FinancialReader

    content, manifest = remote
    manifest.side_effect = AssertionError("local parse must remain offline")
    target = tmp_path / "report.dat"
    target.write_bytes(b"local dat")
    reader = Mock(return_value="parsed locally")
    monkeypatch.setattr(FinancialReader, "to_data", reader)
    assert Affair.parse(tmp_path, target.name, header="en") == "parsed locally"
    reader.assert_called_once_with(target, header="en")
    content.assert_not_called()
    manifest.assert_not_called()


def test_parse_missing_file_validates_download_before_calling_reader(tmp_path, remote, monkeypatch):
    from tdxhub.financial.financial import FinancialReader

    content, manifest = remote
    reader = Mock(return_value="parsed after verification")
    monkeypatch.setattr(FinancialReader, "to_data", reader)
    content.return_value = b"x" * len(PAYLOAD)
    with pytest.raises(OSError, match="MD5 校验失败"):
        Affair.parse(tmp_path, "report.zip")
    reader.assert_not_called()
    assert not (tmp_path / "report.zip").exists()
    content.return_value = PAYLOAD
    assert Affair.parse(tmp_path, "report.zip") == "parsed after verification"
    reader.assert_called_once_with(tmp_path / "report.zip")
    assert manifest.call_count == 2
