from __future__ import annotations

from tdxhub.tools import DownloadTDXCaiWu as downloader


class FakeResponse:
    headers: dict[str, str] = {}
    content = b"financial-data"

    def __init__(self):
        self.raise_for_status_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True


def test_download_file_uses_httpx_and_checks_response(monkeypatch, tmp_path):
    response = FakeResponse()
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(downloader.httpx, "get", fake_get)

    url = "https://example.test/gpcw.txt"
    downloader.DownloadTDXCaiWu.download_file(url, tmp_path, "")

    assert calls == [
        (
            url,
            {
                "follow_redirects": True,
                "timeout": downloader.DOWNLOAD_TIMEOUT,
            },
        )
    ]
    assert response.raise_for_status_called is True
    assert (tmp_path / "gpcw.txt").read_bytes() == response.content
