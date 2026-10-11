from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from core.auth import TokenVerifier
from core.contracts import ContractSchemas
from core.errors import ApiError
from core.settings import Settings
from core.storage import ObjectStore
from providers.base import DetectionProvider, GenerationProvider


@dataclass
class AppDeps:
    settings: Settings
    pool: AsyncConnectionPool[AsyncConnection[DictRow]]
    store: ObjectStore
    detector: DetectionProvider | None
    generator: GenerationProvider | None
    contracts: ContractSchemas
    verifier: TokenVerifier | None = None
    http_client: httpx.AsyncClient | None = None
    pool_needs_open: bool = False


_bearer = HTTPBearer(auto_error=False)


def get_deps(request: Request) -> AppDeps:
    deps: AppDeps = request.app.state.deps
    return deps


async def get_owner_uid(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    deps = get_deps(request)
    verifier = deps.verifier
    if verifier is None or creds is None or creds.scheme.lower() != "bearer":
        raise ApiError(401, "unauthenticated")
    return await verifier.verify(creds.credentials)


OwnerUid = Annotated[str, Depends(get_owner_uid)]
Deps = Annotated[AppDeps, Depends(get_deps)]
