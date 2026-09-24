"""Validate financial download metadata and bytes before publishing a file."""

import hashlib
import re
from pathlib import Path


def validate_financial_metadata(filesize=0, expected_md5=None):
    """Low-level downloads may omit metadata; malformed supplied values fail."""
    if isinstance(filesize, bool) or not isinstance(filesize, int) or filesize < 0:
        raise ValueError("filesize 必须为非负整数（0 表示未知）")
    if expected_md5 is not None:
        if not isinstance(expected_md5, str) or re.fullmatch(r"[0-9a-fA-F]{32}", expected_md5) is None:
            raise ValueError("财务文件 MD5 必须为 32 位十六进制字符串")
        expected_md5 = expected_md5.lower()
    return filesize, expected_md5


def verify_financial_stream(stream, *, filename, filesize=0, expected_md5=None):
    """Verify a seekable binary stream without opening a second file handle."""
    filesize, expected_md5 = validate_financial_metadata(filesize, expected_md5)
    actual_size = stream.seek(0, 2)
    if filesize and actual_size != filesize:
        raise OSError(f"财务文件长度校验失败: {filename}，期望 {filesize}，实际 {actual_size}")
    if expected_md5 is not None:
        stream.seek(0)
        digest = hashlib.md5()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != expected_md5:
            raise OSError(f"财务文件 MD5 校验失败: {filename}")


def verify_financial_file(path: str | Path, *, filesize=0, expected_md5=None):
    """Check the same file handle's byte length and, when supplied, MD5."""
    path = Path(path)
    with path.open("rb") as stream:
        verify_financial_stream(stream, filename=path.name, filesize=filesize, expected_md5=expected_md5)
