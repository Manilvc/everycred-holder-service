from pathlib import Path

import pytest

from app.core.storage import InvalidObjectKeyError, LocalStorage


async def test_local_storage_writes_and_builds_url(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, "http://127.0.0.1:8040/media/")

    await storage.put("holders/1/file.json", b"{}", "application/json")

    assert (tmp_path / "holders/1/file.json").read_bytes() == b"{}"
    assert await storage.url_for("holders/1/file.json") == (
        "http://127.0.0.1:8040/media/holders/1/file.json"
    )


@pytest.mark.parametrize("key", ["../escape.txt", "/etc/passwd", ""])
async def test_local_storage_refuses_keys_outside_root(
    tmp_path: Path, key: str
) -> None:
    storage = LocalStorage(tmp_path, "http://127.0.0.1:8040/media")

    with pytest.raises(InvalidObjectKeyError):
        await storage.put(key, b"x", "text/plain")
