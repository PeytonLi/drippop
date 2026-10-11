import base64
import json
import logging
import math
import os
import re
import time
from collections.abc import Mapping
from typing import Any, TypeGuard

import httpx

from providers.base import PreparedImage

DEFAULT_MODEL = "gemini-3.8-flash"
MODEL_ENV_VAR = "GEMINI_MODEL"
_MODEL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,63}$")
MAX_FRAME_BYTES = 15 * 1024 * 1024
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
PROMPT = (
    "Find every clearly visible person and their visible garments. For each person "
    "and garment, provide box_2d as [ymin, xmin, ymax, xmax] integer coordinates "
    "normalized from 0 to 1000 against the full image. Use garment categories only "
    "from the supplied enum. Do not provide names, identities, ages, or other "
    "attributes."
)
BOX = {
    "type": "array",
    "minItems": 4,
    "maxItems": 4,
    "items": {"type": "integer", "minimum": 0, "maximum": 1000},
}
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "persons": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "box_2d": BOX,
                    "garments": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "enum": [
                                        "upper_body",
                                        "full_body",
                                        "lower_body",
                                        "shoes",
                                        "outer",
                                    ],
                                },
                                "box_2d": BOX,
                            },
                            "required": ["category", "box_2d"],
                        },
                    },
                },
                "required": ["box_2d", "garments"],
            },
        }
    },
    "required": ["persons"],
}
GARMENT_CATEGORIES = frozenset({"upper_body", "full_body", "lower_body", "shoes", "outer"})
logger = logging.getLogger("drippop.providers.gemini")


def _validate_model(model: str) -> str:
    if not _MODEL_ID_PATTERN.fullmatch(model):
        raise ValueError("invalid Gemini model ID")
    return model


def resolve_model(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    model = source.get(MODEL_ENV_VAR)
    return _validate_model(model) if model else DEFAULT_MODEL


class DetectionUnavailable(Exception):
    def __init__(self, safe_code: str = "analysis_unavailable", retryable: bool = True):
        self.safe_code = safe_code
        self.retryable = retryable
        super().__init__(safe_code, retryable)


class GeminiDetectionProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key
        self.model = _validate_model(resolve_model() if model is None else model)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = client or httpx.AsyncClient(follow_redirects=False, timeout=timeout)
        self.client.headers.pop("Authorization", None)

    def _log(
        self,
        status: int | None,
        outcome: str,
        started: float,
        usage: dict[str, Any] | None = None,
    ) -> None:
        usage = usage or {}
        prompt_tokens = usage.get("promptTokenCount")
        output_tokens = usage.get("candidatesTokenCount")
        if type(prompt_tokens) is not int:
            prompt_tokens = None
        if type(output_tokens) is not int:
            output_tokens = None
        logger.info(
            "status=%s outcome_code=%s duration_ms=%d prompt_tokens=%s output_tokens=%s",
            status,
            outcome,
            int((time.perf_counter() - started) * 1000),
            prompt_tokens,
            output_tokens,
        )

    def _manual(self, frame: PreparedImage) -> dict[str, Any]:
        return {
            "image_width": frame.width,
            "image_height": frame.height,
            "coordinate_space": "normalized_upright_xyxy",
            "persons": [],
            "manual_selection_required": True,
        }

    def _valid_box(self, value: Any) -> TypeGuard[list[int | float]]:
        if not isinstance(value, list) or len(value) != 4:
            return False
        if any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or item < 0
            or item > 1000
            or not math.isfinite(item)
            for item in value
        ):
            return False
        return bool(value[0] < value[2] and value[1] < value[3])

    def _convert_box(self, value: list[int | float]) -> list[float]:
        ymin, xmin, ymax, xmax = value
        return [xmin / 1000, ymin / 1000, xmax / 1000, ymax / 1000]

    def _parse_model_text(self, text: str, frame: PreparedImage) -> dict[str, Any]:
        try:
            value = json.loads(text)
        except (ValueError, json.JSONDecodeError):
            return self._manual(frame)
        if not isinstance(value, dict):
            return self._manual(frame)
        persons = value.get("persons")
        if not isinstance(persons, list) or not persons or len(persons) > 8:
            return self._manual(frame)

        seen_people: set[tuple[int | float, ...]] = set()
        converted_persons: list[dict[str, Any]] = []
        garment_id = 0
        for person_index, person in enumerate(persons, start=1):
            if not isinstance(person, dict):
                return self._manual(frame)
            person_box = person.get("box_2d")
            if not self._valid_box(person_box):
                return self._manual(frame)
            person_box_key = tuple(person_box)
            if person_box_key in seen_people:
                return self._manual(frame)
            seen_people.add(person_box_key)

            garments = person.get("garments")
            if not isinstance(garments, list) or len(garments) > 8:
                return self._manual(frame)
            seen_garments: set[tuple[str, tuple[int | float, ...]]] = set()
            converted_garments: list[dict[str, Any]] = []
            for garment in garments:
                if not isinstance(garment, dict):
                    return self._manual(frame)
                category = garment.get("category")
                box = garment.get("box_2d")
                if (
                    not isinstance(category, str)
                    or category not in GARMENT_CATEGORIES
                    or not self._valid_box(box)
                ):
                    return self._manual(frame)
                garment_key = (category, tuple(box))
                if garment_key in seen_garments:
                    return self._manual(frame)
                seen_garments.add(garment_key)
                garment_id += 1
                converted_garments.append(
                    {
                        "id": f"g{garment_id}",
                        "category": category,
                        "box": self._convert_box(box),
                    }
                )
            converted_persons.append(
                {
                    "id": f"p{person_index}",
                    "box": self._convert_box(person_box),
                    "garments": converted_garments,
                }
            )
        return {
            "image_width": frame.width,
            "image_height": frame.height,
            "coordinate_space": "normalized_upright_xyxy",
            "persons": converted_persons,
            "manual_selection_required": False,
        }

    async def detect(self, frame: PreparedImage) -> dict[str, Any]:
        started = time.perf_counter()
        if len(frame.data) > MAX_FRAME_BYTES:
            self._log(None, "analysis_unavailable", started)
            raise DetectionUnavailable(retryable=False)

        endpoint = f"{self.base_url}/v1beta/models/{self.model}:generateContent"
        request_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": frame.mime,
                                "data": base64.b64encode(frame.data).decode("ascii"),
                            }
                        },
                        {"text": PROMPT},
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": RESPONSE_SCHEMA,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }
        try:
            response = await self.client.post(
                endpoint,
                headers={"x-goog-api-key": self.api_key},
                json=request_body,
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            self._log(None, "analysis_unavailable", started)
            raise DetectionUnavailable(retryable=True) from exc

        status = response.status_code
        if not 200 <= status < 300:
            retryable = status == 429 or status >= 500
            self._log(status, "analysis_unavailable", started)
            raise DetectionUnavailable(retryable=retryable)
        try:
            envelope = response.json()
        except (ValueError, json.JSONDecodeError):
            self._log(status, "analysis_unavailable", started)
            raise DetectionUnavailable(retryable=True) from None
        if not isinstance(envelope, dict):
            self._log(status, "analysis_unavailable", started)
            raise DetectionUnavailable(retryable=True)
        usage = envelope.get("usageMetadata")
        usage = usage if isinstance(usage, dict) else None

        prompt_feedback = envelope.get("promptFeedback")
        if isinstance(prompt_feedback, dict) and prompt_feedback.get("blockReason") is not None:
            self._log(status, "manual_selection_required", started, usage)
            return self._manual(frame)
        candidates = envelope.get("candidates")
        if not isinstance(candidates, list):
            self._log(status, "analysis_unavailable", started, usage)
            raise DetectionUnavailable(retryable=True)
        if not candidates:
            self._log(status, "manual_selection_required", started, usage)
            return self._manual(frame)
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            self._log(status, "manual_selection_required", started, usage)
            return self._manual(frame)
        if "finishReason" in candidate and candidate.get("finishReason") != "STOP":
            self._log(status, "manual_selection_required", started, usage)
            return self._manual(frame)
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        parts = parts if isinstance(parts, list) else []
        text = "".join(
            part["text"]
            for part in parts
            if isinstance(part, dict)
            and part.get("thought") is not True
            and isinstance(part.get("text"), str)
        )
        if not text.strip():
            self._log(status, "manual_selection_required", started, usage)
            return self._manual(frame)
        output = self._parse_model_text(text, frame)
        outcome = "manual_selection_required" if output["manual_selection_required"] else "ok"
        self._log(status, outcome, started, usage)
        return output
