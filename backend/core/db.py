import sys
from pathlib import Path

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from core.settings import Settings

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def make_pool(database_url: str, *, max_size: int = 10) -> Pool:
    return AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=max_size,
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
        open=False,
    )


async def apply_migrations(database_url: str, migrations_dir: Path | None = None) -> list[str]:
    migrations_dir = migrations_dir or _MIGRATIONS_DIR
    files = sorted(migrations_dir.glob("*.sql"))
    applied: list[str] = []
    async with await psycopg.AsyncConnection.connect(
        database_url, autocommit=True, prepare_threshold=None
    ) as conn:
        await conn.execute(
            "create table if not exists public._drippop_migrations "
            "(name text primary key, applied_at timestamptz not null default now())"
        )
        rows = await conn.execute("select name from public._drippop_migrations")
        done = {r[0] for r in await rows.fetchall()}
        for f in files:
            if f.name in done:
                continue
            await conn.execute(f.read_text())
            await conn.execute(
                "insert into public._drippop_migrations (name) values (%s)", (f.name,)
            )
            applied.append(f.name)
    return applied


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "migrate":
        import asyncio

        settings = Settings()
        applied = asyncio.run(apply_migrations(settings.database_url))
        for name in applied:
            print(f"applied {name}")
        if not applied:
            print("no pending migrations")
        return 0
    print("usage: python -m core.db migrate", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
