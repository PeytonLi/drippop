"""Live provider wiring for PROVIDER_MODE=live.

Each provider is built only when its API key is configured; all other knobs stay
at the adapter defaults (see providers/youcam.py, providers/gemini.py).
"""

from typing import Any, cast

from core.settings import Settings
from providers.base import DetectionProvider, GenerationProvider
from providers.gemini import GeminiDetectionProvider
from providers.youcam import YouCamGenerationProvider


def build_live_providers(
    settings: Settings,
) -> tuple[DetectionProvider | None, GenerationProvider | None]:
    detector: DetectionProvider | None = None
    if settings.gemini_api_key:
        detector = cast(
            DetectionProvider,
            GeminiDetectionProvider(settings.gemini_api_key, model=settings.gemini_model),
        )
    generator: GenerationProvider | None = None
    if settings.youcam_api_key:
        generator = cast(GenerationProvider, YouCamGenerationProvider(settings.youcam_api_key))
    return detector, generator


async def aclose_providers(*providers: Any) -> None:
    for provider in providers:
        if provider is not None:
            await provider.client.aclose()
