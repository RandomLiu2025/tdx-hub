"""Keep server-supplied financial filenames inside the caller's directory."""

import tempfile
from pathlib import Path, PureWindowsPath

from .financial_integrity import validate_financial_metadata, verify_financial_file


def validate_financial_filename(filename: str) -> str:
    """Accept a portable basename, never a local path or remote subdirectory."""
    if (
        not isinstance(filename, str)
        or not filename
        or filename in {".", ".."}
        or any(char in filename for char in '/\\:<>"|?*')
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
        or filename.endswith((".", " "))
        or PureWindowsPath(filename).is_reserved()
    ):
        raise ValueError(f"非法财务文件名（只允许普通文件名）: {filename!r}")
    return filename


def financial_download_path(directory: str | Path, filename: str) -> Path:
    """Validate before reading cached files, downloading, deleting or writing."""
    validate_financial_filename(filename)
    root = Path(directory).resolve()
    target = root / filename
    if target.is_symlink() or target.resolve().parent != root:
        raise ValueError(f"财务文件路径越界或为符号链接: {filename!r}")
    if target.exists() and not target.is_file():
        raise ValueError(f"财务文件目标不是普通文件: {filename!r}")
    # Preserve the public relative-path return convention.
    return Path(directory) / filename


def write_financial_download(
    directory: str | Path, filename: str, content: bytes, *, filesize=0, expected_md5=None,
):
    """Stage, verify supplied metadata, then replace without following links.

    The caller controls/trusts the download directory and its ancestors. Remote
    filenames and existing target entries are untrusted. Atomic replacement also
    prevents truncating other files through an existing hard link.
    """
    filesize, expected_md5 = validate_financial_metadata(filesize, expected_md5)
    root = Path(directory).resolve()
    target = financial_download_path(root, filename)
    root.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=".tdxhub-", suffix=".tmp", delete=False) as stream:
            staged = Path(stream.name)
            stream.write(content)
        verify_financial_file(staged, filesize=filesize, expected_md5=expected_md5)
        # The download may have taken a while; do not trust an earlier path check.
        financial_download_path(root, filename)
        staged.replace(target)
        return target.open("rb")
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
