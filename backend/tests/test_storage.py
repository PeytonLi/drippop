from typing import Any

import httpx
import pytest

from core.storage import (
    LocalObjectStore,
    ObjectNotFound,
    SupabaseObjectStore,
)


async def test_local_put_get_delete(tmp_path):
    store = LocalObjectStore(tmp_path)
    await store.put("jobs/j1/person.jpg", b"abc", "image/jpeg")
    assert await store.get("jobs/j1/person.jpg") == b"abc"
    infos = await store.list_prefix("jobs/", 10)
    assert [i.name for i in infos] == ["jobs/j1/person.jpg"]
    await store.delete("jobs/j1/person.jpg")
    with pytest.raises(ObjectNotFound):
        await store.get("jobs/j1/person.jpg")
    await store.delete("jobs/j1/person.jpg")  # missing ok


async def test_path_traversal_rejected(tmp_path):
    store = LocalObjectStore(tmp_path)
    for bad in ("../x", "a/../../b", "/abs", "a b"):
        with pytest.raises(ValueError):
            await store.put(bad, b"x", "image/jpeg")


def _supa(handler):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://proj.supabase.co/storage/v1"
    )
    return SupabaseObjectStore(
        "https://proj.supabase.co", "sb_secret_x", "drippop-private", client=client
    )


async def test_supa_put_headers_and_path():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={})

    store = _supa(handler)
    await store.put("jobs/j/result.jpg", b"data", "image/jpeg")
    assert seen["method"] == "POST"
    assert seen["path"] == "/storage/v1/object/drippop-private/jobs/j/result.jpg"
    assert seen["headers"].get("apikey") == "sb_secret_x"
    assert "authorization" not in seen["headers"]
    assert seen["headers"].get("x-upsert") == "true"


async def test_supa_get_and_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        if "missing" in request.url.path:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, content=b"img")

    store = _supa(handler)
    assert await store.get("jobs/j/a.jpg") == b"img"
    with pytest.raises(ObjectNotFound):
        await store.get("jobs/missing/a.jpg")


async def test_supa_list_prefix_recurses_folders():
    """/object/list is non-recursive: folder entries (id null) must be descended."""

    def handler(request: httpx.Request) -> httpx.Response:
        prefix = __import__("json").loads(request.content)["prefix"]
        if prefix == "jobs/":
            return httpx.Response(200, json=[{"name": "abc123", "id": None}])
        if prefix == "jobs/abc123/":
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "person.jpg",
                        "id": "obj-1",
                        "updated_at": "2026-10-11T00:00:00Z",
                    }
                ],
            )
        return httpx.Response(200, json=[])

    store = _supa(handler)
    infos = await store.list_prefix("jobs/", 10)
    assert [i.name for i in infos] == ["jobs/abc123/person.jpg"]


async def test_supa_delete_and_list():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[{"name": "x.jpg", "id": "obj-1", "updated_at": "2026-10-11T00:00:00Z"}],
        )

    store = _supa(handler)
    await store.delete("jobs/j/a.jpg")
    infos = await store.list_prefix("jobs/", 5)
    assert infos[0].name.endswith("x.jpg")
    methods = {m for m, _ in seen}
    assert "DELETE" in methods and "POST" in methods
