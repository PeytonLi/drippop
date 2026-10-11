import httpx

import core.smoke as smoke
from tests.conftest import make_token


async def test_smoke_passes_against_local_fakes(
    settings, test_database_url, jwks_doc, ec_key, monkeypatch, capsys
):
    settings.database_url = test_database_url
    settings.supabase_secret_key = "sb_secret_x"  # noqa: S105 — fake test key

    def jwks_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jwks_doc)

    objs: dict[str, bytes] = {}

    def storage_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and "/object/" in path and "/list/" not in path:
            objs[path.split("/object/drippop-private/")[-1]] = request.content
            return httpx.Response(200, json={})
        if request.method == "GET":
            key = path.split("/object/drippop-private/")[-1]
            if key in objs:
                return httpx.Response(200, content=objs[key])
            return httpx.Response(404, json={})
        if request.method == "DELETE":
            import json

            for p in json.loads(request.content)["prefixes"]:
                objs.pop(p, None)
            return httpx.Response(200, json=[])
        return httpx.Response(400, json={})

    jwks_client = httpx.AsyncClient(transport=httpx.MockTransport(jwks_handler))
    storage_client = httpx.AsyncClient(
        transport=httpx.MockTransport(storage_handler),
        base_url="https://proj.supabase.co/storage/v1",
    )

    # emulate the Supabase storage.buckets catalog for the smoke DB check
    import psycopg

    async with await psycopg.AsyncConnection.connect(test_database_url, autocommit=True) as conn:
        await conn.execute("create schema if not exists storage")
        await conn.execute(
            "create table if not exists storage.buckets"
            " (id text primary key, name text, public boolean)"
        )
        await conn.execute(
            "insert into storage.buckets values ('drippop-private','drippop-private',false)"
            " on conflict (id) do nothing"
        )
        # grant usage so the smoke role can read it
        await conn.execute("grant usage on schema storage to public")
        await conn.execute("grant select on storage.buckets to public")

    monkeypatch.setattr(smoke, "Settings", lambda: settings)
    smoke._results.clear()
    token = make_token("smoke-user", priv=ec_key)
    code = await smoke.run_smoke(token, jwks_client=jwks_client, storage_client=storage_client)
    out = capsys.readouterr().out
    assert "sb_secret_x" not in out
    assert "sub_hash=" in out
    assert "smoke-user" not in out
    assert code == 0, out
