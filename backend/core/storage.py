import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx

_VALID_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")


class ObjectNotFound(Exception):
    pass


@dataclass(frozen=True)
class StoredObjectInfo:
    name: str
    updated_at: datetime


def check_path(path: str) -> None:
    if not _VALID_PATH.match(path) or ".." in path or path.startswith("/"):
        raise ValueError("invalid object path")


class ObjectStore(Protocol):
    async def put(self, path: str, data: bytes, content_type: str) -> None: ...
    async def get(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> None: ...
    async def list_prefix(self, prefix: str, limit: int) -> list[StoredObjectInfo]: ...


class LocalObjectStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        check_path(path)
        resolved = (self.root / path).resolve()
        if not str(resolved).startswith(str(self.root.resolve()) + os.sep):
            raise ValueError("invalid object path")
        return resolved

    async def put(self, path: str, data: bytes, content_type: str) -> None:
        dest = self._resolve(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dest.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    async def get(self, path: str) -> bytes:
        try:
            return self._resolve(path).read_bytes()
        except FileNotFoundError:
            raise ObjectNotFound(path) from None

    async def delete(self, path: str) -> None:
        try:
            self._resolve(path).unlink()
        except FileNotFoundError:
            pass

    async def list_prefix(self, prefix: str, limit: int) -> list[StoredObjectInfo]:
        base = self._resolve(prefix) if prefix else self.root
        out: list[StoredObjectInfo] = []
        if not base.exists():
            return out
        candidates = [base] if base.is_file() else sorted(base.rglob("*"))
        for p in candidates:
            if p.is_file():
                rel = p.relative_to(self.root).as_posix()
                out.append(
                    StoredObjectInfo(
                        name=rel,
                        updated_at=datetime.fromtimestamp(p.stat().st_mtime).astimezone(),
                    )
                )
                if len(out) >= limit:
                    break
        return out


class SupabaseObjectStore:
    def __init__(
        self,
        supabase_url: str,
        secret_key: str,
        bucket: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.bucket = bucket
        if client is None:
            client = httpx.AsyncClient(
                base_url=supabase_url + "/storage/v1",
                timeout=httpx.Timeout(connect=5, read=30, write=30, pool=5),
            )
        self._client = client
        self._headers = {"apikey": secret_key}

    async def put(self, path: str, data: bytes, content_type: str) -> None:
        check_path(path)
        resp = await self._client.post(
            f"/object/{self.bucket}/{path}",
            content=data,
            headers={**self._headers, "x-upsert": "true", "content-type": content_type},
        )
        resp.raise_for_status()

    async def get(self, path: str) -> bytes:
        check_path(path)
        resp = await self._client.get(f"/object/{self.bucket}/{path}", headers=self._headers)
        if resp.status_code in (400, 404):
            raise ObjectNotFound(path)
        resp.raise_for_status()
        return resp.content

    async def delete(self, path: str) -> None:
        check_path(path)
        resp = await self._client.request(
            "DELETE",
            f"/object/{self.bucket}",
            json={"prefixes": [path]},
            headers=self._headers,
        )
        resp.raise_for_status()

    async def list_prefix(self, prefix: str, limit: int) -> list[StoredObjectInfo]:
        return await self._list(prefix, limit)

    async def _list(self, prefix: str, limit: int) -> list[StoredObjectInfo]:
        """List files under prefix; /object/list is non-recursive, so folder
        entries (id null) are descended into one level at a time."""
        resp = await self._client.post(
            f"/object/list/{self.bucket}",
            json={"prefix": prefix, "limit": limit},
            headers=self._headers,
        )
        resp.raise_for_status()
        out: list[StoredObjectInfo] = []
        for item in resp.json():
            if len(out) >= limit:
                break
            name = item.get("name")
            if not isinstance(name, str):
                continue
            if item.get("id") is None:
                out.extend(await self._list(f"{prefix.rstrip('/')}/{name}/", limit - len(out)))
                continue
            updated = item.get("updated_at") or item.get("created_at") or ""
            try:
                ts = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.fromtimestamp(0).astimezone()
            out.append(StoredObjectInfo(name=f"{prefix.rstrip('/')}/{name}", updated_at=ts))
        return out
