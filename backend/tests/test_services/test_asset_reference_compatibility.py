"""Real compatibility baseline for asset URL extraction and storage key conversion."""

from __future__ import annotations

import pytest

from app.services.asset_reference_service import (
    extract_asset_urls,
    url_to_storage_key,
)


class TestUrlToStorageKey:
    def test_static_url_stripped(self):
        result = url_to_storage_key("/static/question-assets/202607/q_1.png")
        assert result == "question-assets/202607/q_1.png"

    def test_full_static_url_stripped(self):
        result = url_to_storage_key("https://cdn.example.com/static/question-assets/q.png")
        assert result == "question-assets/q.png"

    def test_cos_url_stripped(self):
        result = url_to_storage_key(
            "https://bucket.cos.ap-shanghai.myqcloud.com/question-assets/q.png"
        )
        assert result == "question-assets/q.png"

    def test_plain_url_lstrip_slash(self):
        result = url_to_storage_key("/some/path/file.png")
        assert result == "some/path/file.png"

    def test_no_leading_slash(self):
        result = url_to_storage_key("path/file.png")
        assert result == "path/file.png"


class TestExtractAssetUrls:
    def test_empty_dict_returns_empty(self):
        assert extract_asset_urls({}) == []

    def test_static_asset_in_string(self):
        results = extract_asset_urls("/static/question-assets/q_1.png")
        assert len(results) == 1
        assert "question-assets" in results[0]["url"]

    def test_cos_asset_in_string(self):
        url = "https://bucket.cos.ap-shanghai.myqcloud.com/question-assets/q.png"
        results = extract_asset_urls(url)
        assert len(results) == 1

    def test_nested_dict(self):
        obj = {"content": {"image": "/static/question-assets/img.png"}}
        results = extract_asset_urls(obj)
        assert len(results) == 1
        assert "content.image" in results[0]["json_path"]

    def test_list_items(self):
        obj = ["/static/question-assets/a.png", "/static/question-assets/b.png"]
        results = extract_asset_urls(obj)
        assert len(results) == 2

    def test_no_assets_returns_empty(self):
        assert extract_asset_urls({"text": "hello world"}) == []

    def test_multiple_assets_in_same_string(self):
        text = "/static/question-assets/a.png and /static/question-assets/b.png"
        results = extract_asset_urls(text)
        assert len(results) == 2

    def test_field_name_in_path(self):
        results = extract_asset_urls("/static/question-assets/q.png", field_name="content")
        assert results[0]["json_path"] == "content"
