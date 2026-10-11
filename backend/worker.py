import argparse
import asyncio
import signal
import time
from typing import Any

from core.contracts import ContractSchemas
from core.db import make_pool
from core.dispatch import WorkerDeps, claim, drain, handle_dispatch, reconcile
from core.logging import configure_logging, log
from core.settings import Settings
from core.storage import LocalObjectStore, SupabaseObjectStore
from providers.fake import FakeDetectionProvider, FakeGenerationProvider
from providers.live import aclose_providers, build_live_providers


def build_deps(settings: Settings) -> WorkerDeps:
    contracts = ContractSchemas(settings.contracts_dir)
    pool = make_pool(settings.database_url)
    if settings.storage_backend == "supabase":
        store: Any = SupabaseObjectStore(
            settings.supabase_url, settings.supabase_secret_key, settings.storage_bucket
        )
    else:
        store = LocalObjectStore(settings.local_storage_dir)
    if settings.provider_mode == "fake":
        detector: Any = FakeDetectionProvider()
        generator: Any = FakeGenerationProvider()
    else:
        detector, generator = build_live_providers(settings)
    return WorkerDeps(
        settings=settings,
        pool=pool,
        store=store,
        generator=generator,
        detector=detector,
        contracts=contracts,
    )


async def run_loop(deps: WorkerDeps) -> None:
    stop = asyncio.Event()

    def _sigterm() -> None:
        stop.set()

    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, _sigterm)
    last_reconcile = 0.0

    while not stop.is_set():
        try:
            async with deps.pool.connection() as conn, conn.transaction():
                dispatch = await claim(conn, deps.settings.lease_s)
            if dispatch is not None:
                outcome = await handle_dispatch(deps, dispatch)
                log(
                    "dispatch_handled",
                    dispatch_id=dispatch["id"],
                    job_id=dispatch["job_id"],
                    outcome=outcome,
                )
            else:
                if time.monotonic() - last_reconcile > deps.settings.reconcile_interval_s:
                    await reconcile(deps)
                    last_reconcile = time.monotonic()
                try:
                    await asyncio.wait_for(stop.wait(), deps.settings.worker_idle_sleep_s)
                except TimeoutError:
                    pass
        except Exception as exc:
            log("worker_loop_error", level=40, error=exc.__class__.__name__)
            await asyncio.sleep(deps.settings.worker_idle_sleep_s)


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="worker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    drain_p = sub.add_parser("drain")
    drain_p.add_argument("--max-steps", type=int, default=None)
    sub.add_parser("reconcile")
    args = parser.parse_args()

    settings = Settings()
    deps = build_deps(settings)

    async def _main() -> None:
        await deps.pool.open()
        try:
            if args.command == "run":
                await run_loop(deps)
            elif args.command == "drain":
                n = await drain(deps, args.max_steps)
                log("drain_complete", handled=n)
            elif args.command == "reconcile":
                counts = await reconcile(deps)
                log("reconcile_complete", **counts)
        finally:
            await deps.pool.close()
            await aclose_providers(deps.detector, deps.generator)

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
