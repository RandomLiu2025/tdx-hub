"""Download and parse TDX financial archives."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tdxhub.financial import financial
from tdxhub.logger import logger
from tdxhub.tdx.financial_integrity import validate_financial_metadata, verify_financial_file
from tdxhub.tdx.financial_path import financial_download_path
from tdxhub.utils import TqdmUpTo


def _manifest_entry(downdir: str | Path, item: dict) -> dict:
    if not isinstance(item, Mapping):
        raise ValueError("财务清单条目必须为映射")
    financial_download_path(downdir, item.get("filename"))
    filesize, digest = validate_financial_metadata(item.get("filesize"), item.get("hash"))
    if not filesize or digest is None:
        raise ValueError(f"财务清单缺少有效长度或 MD5: {item['filename']}")
    return {"filename": item["filename"], "filesize": filesize, "hash": digest}


def _validated_manifest(downdir: str | Path, manifest: list[dict]) -> list[dict]:
    # Deduplicate before scheduling. Portable aliases must not race to replace
    # one destination on case-insensitive / Unicode-normalizing filesystems.
    entries = {}
    for item in manifest:
        entry = _manifest_entry(downdir, item)
        key = unicodedata.normalize("NFC", entry["filename"]).casefold()
        previous = entries.get(key)
        if previous is not None and previous != entry:
            raise ValueError(f"财务清单存在重复文件名或校验信息冲突: {entry['filename']}")
        entries[key] = entry
    return list(entries.values())


def download(downdir: str | Path, filename: str) -> bool:
    financial_download_path(downdir, filename)
    Affair.fetch(downdir=downdir, filename=filename)
    return True


def fetch_file(downdir: str | Path, file_obj: dict, *, report_hook=None):
    """Reuse a verified copy, or verify a staged download before replacement."""
    entry = _manifest_entry(downdir, file_obj)
    filepath = financial_download_path(downdir, entry["filename"])
    if filepath.is_file():
        try:
            verify_financial_file(filepath, filesize=entry["filesize"], expected_md5=entry["hash"])
        except OSError:
            # An invalid/unreadable cache is not deleted. A failed refresh must
            # leave the previous directory entry untouched.
            pass
        else:
            logger.info("文件已存在且校验通过: %s", filepath)
            return filepath

    financial.Financial().fetch_only(
        report_hook=report_hook,
        filename=entry["filename"],
        filesize=entry["filesize"],
        expected_md5=entry["hash"],
        downdir=downdir,
    )
    return filepath


class Affair:
    @staticmethod
    def parse(downdir: str | Path = ".", filename: str | None = None, **kwargs):
        if not filename:
            raise ValueError("filename 不能为空")

        filepath = financial_download_path(downdir, filename)
        if not filepath.is_file():
            Affair.fetch(downdir=downdir, filename=filename)
        if not filepath.is_file():
            raise FileNotFoundError(filepath)
        return financial.FinancialReader().to_data(filepath, **kwargs)

    @staticmethod
    def files() -> list[dict]:
        return financial.FinancialList().fetch_and_parse() or []

    @staticmethod
    def fetch(downdir: str | Path | None = None, filename: str | None = None):
        destination = Path(downdir or ".")
        if filename is not None:
            financial_download_path(destination, filename)

        # Single-file and batch downloads share one validated manifest snapshot.
        # A missing entry must not silently downgrade to an unchecked download.
        manifest = _validated_manifest(destination, Affair.files())
        if filename:
            entry = next((item for item in manifest if item["filename"] == filename), None)
            if entry is None:
                raise FileNotFoundError(f"财务清单中不存在文件: {filename}")
            with TqdmUpTo(unit="B", unit_scale=True, miniters=1, ascii=True) as progress:
                return fetch_file(destination, entry, report_hook=progress.update_to)

        workers = min(8, max(1, len(manifest)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tdxhub-finance") as pool:
            return list(pool.map(lambda item: fetch_file(destination, item), manifest))
