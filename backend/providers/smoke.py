import argparse
import asyncio
import json
import os
import sys
import time
from importlib import import_module
from pathlib import Path
from typing import Literal

from providers.base import (
    Failed,
    Pending,
    PreparedImage,
    ProviderTicket,
    SubmitAmbiguous,
    SubmitRejected,
)
from providers.gemini import (
    DetectionUnavailable,
    GeminiDetectionProvider,
    resolve_model,
)
from providers.youcam import (
    DownloadError,
    YouCamGenerationProvider,
)

MAX_DEADLINE_SECONDS = 600
MAX_OUTPUT_BYTES = 20 * 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[2]
_youcam_submit_attempted = False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Opt-in provider smoke test")
    parser.add_argument("--provider", choices=("youcam", "gemini"), required=True)
    parser.add_argument("--i-accept-cost", action="store_true")
    parser.add_argument("--person")
    parser.add_argument("--reference")
    parser.add_argument("--category", choices=("upper_body", "full_body"), default="upper_body")
    parser.add_argument("--frame")
    parser.add_argument("--deadline-s", type=int, default=180)
    parser.add_argument("--out")
    return parser


def _within_local(path: str) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    local_root = (REPO_ROOT / ".local").resolve()
    try:
        candidate.resolve().relative_to(local_root)
    except ValueError:
        return False
    return True


def _refuse(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _read_image(path: str) -> PreparedImage:
    image_module = import_module("PIL.Image")
    data = Path(path).read_bytes()
    with image_module.open(path) as image:
        mime_types: dict[str, Literal["image/jpeg", "image/png"]] = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
        }
        mime = mime_types.get(image.format or "")
        if mime is None:
            raise ValueError("unsupported image type")
        width, height = image.size
    return PreparedImage(data, mime, width, height)


async def _submit_youcam_once(
    provider: YouCamGenerationProvider,
    person: PreparedImage,
    reference: PreparedImage,
    category: str,
) -> ProviderTicket:
    global _youcam_submit_attempted
    if _youcam_submit_attempted:
        raise RuntimeError("YouCam smoke submit cap reached")
    _youcam_submit_attempted = True
    return await provider.submit(person, reference, category)  # type: ignore[arg-type]


async def _run_youcam(args: argparse.Namespace, key: str) -> int:
    started = time.perf_counter()
    provider = YouCamGenerationProvider(key)
    try:
        person = _read_image(args.person)
        reference = _read_image(args.reference)
        try:
            ticket = await _submit_youcam_once(provider, person, reference, args.category)
        except SubmitRejected as exc:
            print(
                f"outcome=rejected safe_code={exc.args[0]} "
                f"duration_ms={int((time.perf_counter() - started) * 1000)}"
            )
            return 1
        except SubmitAmbiguous:
            duration_ms = int((time.perf_counter() - started) * 1000)
            print(f"outcome=submission_unknown duration_ms={duration_ms}")
            return 1

        deadline = time.monotonic() + args.deadline_s
        while time.monotonic() < deadline:
            result = await provider.check(ticket)
            if isinstance(result, Pending):
                await asyncio.sleep(min(10, max(0, deadline - time.monotonic())))
                continue
            if isinstance(result, Failed):
                print(
                    f"outcome=failed safe_code={result.safe_code} "
                    f"duration_ms={int((time.perf_counter() - started) * 1000)}"
                )
                return 1
            output_path = args.out or ".local/youcam-result"
            data = await provider.download(result.output_url, MAX_OUTPUT_BYTES)
            destination = Path(output_path)
            if not destination.is_absolute():
                destination = REPO_ROOT / destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            print(
                f"outcome=succeeded bytes={len(data)} "
                f"duration_ms={int((time.perf_counter() - started) * 1000)}"
            )
            return 0
        print(
            f"outcome=deadline_exceeded duration_ms={int((time.perf_counter() - started) * 1000)}"
        )
        return 1
    except DownloadError as exc:
        print(
            f"outcome=unavailable safe_code={exc.safe_code} "
            f"duration_ms={int((time.perf_counter() - started) * 1000)}"
        )
        return 1
    except (OSError, ValueError, ImportError):
        print(
            f"outcome=failed safe_code=provider_rejected "
            f"duration_ms={int((time.perf_counter() - started) * 1000)}"
        )
        return 1
    finally:
        await provider.client.aclose()


async def _run_gemini(args: argparse.Namespace, key: str) -> int:
    started = time.perf_counter()
    provider: GeminiDetectionProvider | None = None
    try:
        provider = GeminiDetectionProvider(key, model=resolve_model())
        frame = _read_image(args.frame)
        result = await provider.detect(frame)
        if result["manual_selection_required"]:
            print(
                "outcome=manual_selection_required "
                f"duration_ms={int((time.perf_counter() - started) * 1000)}"
            )
        else:
            print(f"outcome=succeeded duration_ms={int((time.perf_counter() - started) * 1000)}")
        if args.out:
            destination = Path(args.out)
            if not destination.is_absolute():
                destination = REPO_ROOT / destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result))
        return 0
    except DetectionUnavailable as exc:
        print(
            f"outcome=unavailable safe_code={exc.safe_code} "
            f"duration_ms={int((time.perf_counter() - started) * 1000)}"
        )
        return 1
    except (OSError, ValueError, ImportError):
        print(
            "outcome=failed safe_code=provider_rejected "
            f"duration_ms={int((time.perf_counter() - started) * 1000)}"
        )
        return 1
    finally:
        if provider is not None:
            await provider.client.aclose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.i_accept_cost:
        return _refuse("Refusing to call a paid provider without --i-accept-cost.")
    if args.deadline_s <= 0 or args.deadline_s > MAX_DEADLINE_SECONDS:
        return _refuse(f"--deadline-s must be between 1 and {MAX_DEADLINE_SECONDS}.")
    if args.out and not _within_local(args.out):
        return _refuse("--out must be inside the repository's .local/ directory.")
    if args.provider == "youcam":
        key = os.environ.get("YOUCAM_API_KEY")
        if not key:
            return _refuse("YOUCAM_API_KEY is required.")
        if not args.person or not args.reference:
            return _refuse("--person and --reference are required for YouCam.")
        if args.out is None:
            args.out = ".local/youcam-result"
        return asyncio.run(_run_youcam(args, key))
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return _refuse("GEMINI_API_KEY is required.")
    if not args.frame:
        return _refuse("--frame is required for Gemini.")
    return asyncio.run(_run_gemini(args, key))


if __name__ == "__main__":
    raise SystemExit(main())
