import hashlib

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from core.errors import ApiError
from core.settings import Settings


async def reserve_detection(
    conn: AsyncConnection[DictRow], owner_uid: str, settings: Settings
) -> None:
    """Atomically bump detection usage counters; 429 when over cap."""
    uid_scope = f"detect:uid:{hashlib.sha256(owner_uid.encode()).hexdigest()}"
    for scope, cap in (
        ("detect:project", settings.detect_daily_cap_project),
        (uid_scope, settings.detect_daily_cap_per_uid),
    ):
        cur = await conn.execute(
            """
            insert into usage_counters (scope, day, count)
            values (%(scope)s, (now() at time zone 'utc')::date, 1)
            on conflict (scope, day) do update
              set count = usage_counters.count + 1
              where usage_counters.count < %(cap)s
            returning count
            """,
            {"scope": scope, "cap": cap},
        )
        if await cur.fetchone() is None:
            raise ApiError(429, "quota_exceeded", retryable=True)
