import asyncio

import pytest

from app.features.ocr_vl.paddleocr_vl_client import ResultDownloadError, _validate_result_url


@pytest.mark.parametrize(
    "url",
    [
        "https://100.64.0.1/r.jsonl",
        "https://0.0.0.0/r.jsonl",
        "https://198.18.0.1/r.jsonl",
        "https://192.0.2.1/r.jsonl",
        "https://[fc00::1]/r.jsonl",
        "https://[ff02::1]/r.jsonl",
        "https://user:pw@8.8.8.8/r.jsonl",
    ],
)
def test_non_global_or_credentialed_result_urls_rejected(url):
    with pytest.raises(ResultDownloadError):
        asyncio.run(_validate_result_url(url))


def test_global_literal_is_accepted():
    assert asyncio.run(_validate_result_url("https://8.8.8.8/r.jsonl")) == "https://8.8.8.8/r.jsonl"


def test_shared_fetch_helper_also_rejects_multicast():
    from app.services.safe_remote_fetch import UnsafeRemoteURLError, validate_remote_url

    for url in ("https://[ff02::1]/x", "https://224.0.0.1/x"):
        with pytest.raises(UnsafeRemoteURLError):
            validate_remote_url(url)
