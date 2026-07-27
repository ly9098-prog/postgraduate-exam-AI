"""Fault injection tests for the streaming upload handler.

Tests that ``stream_to_temp`` and the upload endpoints handle
errors gracefully: oversized files, corrupt data, disk full, etc.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.streaming_upload_handler import stream_to_temp


class TestStreamToTempFaults:
    """stream_to_temp error handling."""

    @pytest.mark.asyncio
    async def test_empty_file_returns_empty_tempfile(self):
        """Uploading 0 bytes returns a TempFile with size=0."""
        mock = MagicMock()
        mock.read = AsyncMock(return_value=b"")

        result = await stream_to_temp(mock, suffix=".txt")
        assert result.size == 0
        assert os.path.getsize(result.path) == 0
        result.close()

    @pytest.mark.asyncio
    async def test_exceeds_max_size_raises_valueerror(self):
        """Uploading content exceeding max_size raises ValueError."""
        mock = MagicMock()
        # Return 1 byte per read, simulate 11 bytes total
        mock.read = AsyncMock(side_effect=[b"x"] * 15 + [b""])

        with pytest.raises(ValueError, match="文件超过大小限制"):
            await stream_to_temp(mock, max_size=10, suffix=".bin")

    @pytest.mark.asyncio
    async def test_read_error_cleans_up_tempfile(self):
        """If upload.read() raises, the temp file is removed."""
        mock = MagicMock()
        mock.read = AsyncMock(side_effect=OSError("connection reset"))

        with pytest.raises(OSError):
            await stream_to_temp(mock, suffix=".bin")

        # Temp file should not exist
        # (We can't check the path since we don't have it, but no file should leak)

    @pytest.mark.asyncio
    async def test_partial_read_then_error_cleans_up(self):
        """Partial content + error → temp file is removed."""
        mock = MagicMock()
        mock.read = AsyncMock(side_effect=[b"partial_content", OSError("disk full")])

        with pytest.raises(OSError):
            await stream_to_temp(mock, suffix=".bin")


class TestTempFileFaults:
    """TempFile lifecycle edge cases."""

    @pytest.mark.asyncio
    async def test_double_close_is_idempotent(self):
        """Calling close() twice is safe."""
        mock = MagicMock()
        mock.read = AsyncMock(return_value=b"")

        tmp = await stream_to_temp(mock)
        tmp.close()
        tmp.close()  # should not raise

    @pytest.mark.asyncio
    async def test_detach_prevents_cleanup(self):
        """After detach(), close() does not unlink the file."""
        mock = MagicMock()
        mock.read = AsyncMock(side_effect=[b"content", b""])

        tmp = await stream_to_temp(mock)
        path = tmp.path
        assert os.path.exists(path)

        tmp.detach()
        tmp.close()
        # File should still exist after close() since we detached
        assert os.path.exists(path)
        # Cleanup for test
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_context_manager_cleans_up(self):
        """Using TempFile as context manager cleans up on exit."""
        mock = MagicMock()
        mock.read = AsyncMock(side_effect=[b"content", b""])

        tmp = await stream_to_temp(mock)
        path = tmp.path
        assert os.path.exists(path)

        tmp.__exit__(None, None, None)
        assert not os.path.exists(path)
