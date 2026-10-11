import base64
import json
import logging
import math
from pathlib import Path

import httpx
import pytest
import respx
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.providers.base import PreparedImage
from backend.providers.gemini import (
    DEFAULT_MODEL,
    RESPONSE_SCHEMA,
    DetectionUnavailable,
    GeminiDetectionProvider,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures" / "gemini"
CONTRACTS = ROOT / "contracts"
FRAME = PreparedImage(b"synthetic-frame", "image/jpeg", 100, 200)
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent"
SCHEMAS = {
    path.name: json.loads(path.read_text())
    for path in (CONTRACTS / "schemas").glob("*.json")
}
REGISTRY = Registry().with_resources(
    [(schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values()]
    + [(name, Resource.from_contents(schema)) for name, schema in SCHEMAS.items()]
)
DETECTION_VALIDATOR = Draft202012Validator(
    SCHEMAS["detection_response.schema.json"], registry=REGISTRY
)


def envelope(text: str) -> dict:
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": text}]},
            }
        ],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
    }


def semantic_check(value: dict) -> bool:
    persons = value["persons"]
    if not persons and not value["manual_selection_required"]:
        return False
    person_ids = [person["id"] for person in persons]
    garment_ids = [
        garment["id"] for person in persons for garment in person["garments"]
    ]
    if len(person_ids) != len(set(person_ids)) or len(garment_ids) != len(
        set(garment_ids)
    ):
        return False
    for box in [person["box"] for person in persons] + [
        garment["box"] for person in persons for garment in person["garments"]
    ]:
        if box[0] >= box[2] or box[1] >= box[3]:
            return False
    return True


@pytest.mark.asyncio
async def test_happy_path_converts_boxes_and_matches_contract_schema() -> None:
    fixture = json.loads((FIXTURES / "detection_response.json").read_text())
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(ENDPOINT).mock(return_value=httpx.Response(200, json=fixture))
        provider = GeminiDetectionProvider("sentinel-key")
        result = await provider.detect(FRAME)
    assert result == {
        "image_width": 100,
        "image_height": 200,
        "coordinate_space": "normalized_upright_xyxy",
        "persons": [
            {
                "id": "p1",
                "box": [0.2, 0.1, 0.8, 0.9],
                "garments": [
                    {"id": "g1", "category": "upper_body", "box": [0.3, 0.2, 0.7, 0.5]}
                ],
            }
        ],
        "manual_selection_required": False,
    }
    DETECTION_VALIDATOR.validate(result)
    assert semantic_check(result)
    request = route.calls[0].request
    assert request.headers["x-goog-api-key"] == "sentinel-key"
    assert request.url.path == f"/v1beta/models/{DEFAULT_MODEL}:generateContent"
    sent = json.loads(request.content)
    assert sent["contents"][0]["parts"][0]["inlineData"] == {
        "mimeType": "image/jpeg",
        "data": base64.b64encode(FRAME.data).decode(),
    }
    assert sent["contents"][0]["parts"][1]["text"]
    assert sent["generationConfig"] == {
        "responseMimeType": "application/json",
        "responseJsonSchema": RESPONSE_SCHEMA,
        "thinkingConfig": {"thinkingLevel": "low"},
    }


@pytest.mark.asyncio
async def test_multiple_people_assign_global_ids_and_ignore_model_metadata() -> None:
    response = envelope(
        json.dumps(
            {
                "persons": [
                    {
                        "id": "ignore",
                        "box_2d": [0, 0, 1000, 500],
                        "confidence": 0.9,
                        "garments": [
                            {
                                "category": "outer",
                                "box_2d": [100, 10, 400, 450],
                                "id": "x",
                            }
                        ],
                    },
                    {
                        "box_2d": [0, 500, 1000, 1000],
                        "garments": [
                            {"category": "shoes", "box_2d": [800, 600, 950, 900]}
                        ],
                    },
                ]
            }
        )
    )
    with respx.mock(assert_all_called=True) as mock:
        mock.post(ENDPOINT).mock(return_value=httpx.Response(200, json=response))
        result = await GeminiDetectionProvider("test").detect(FRAME)
    assert result["persons"][1]["id"] == "p2"
    assert result["persons"][1]["garments"][0]["id"] == "g2"
    assert "confidence" not in json.dumps(result)
    assert semantic_check(result)
    DETECTION_VALIDATOR.validate(result)


def valid_person() -> dict:
    return {"box_2d": [100, 100, 900, 900], "garments": []}


INVALID_OUTPUTS = [
    "not json",
    "[]",
    "{}",
    json.dumps({"persons": "not-a-list"}),
    json.dumps({"persons": []}),
    json.dumps({"persons": [valid_person() for _ in range(9)]}),
    json.dumps({"persons": [{"box_2d": [0, 0, 0, 1], "garments": []}]}),
    json.dumps({"persons": [{"box_2d": [0, 0, 1001, 1], "garments": []}]}),
    json.dumps({"persons": [{"box_2d": [0, 0, True, 1], "garments": []}]}),
    json.dumps({"persons": [{"box_2d": [0, 0, math.inf, 1], "garments": []}]}),
    json.dumps({"persons": [{"box_2d": [0, 0, math.nan, 1], "garments": []}]}),
    json.dumps({"persons": [{"box_2d": [0, 0, "1", 1], "garments": []}]}),
    json.dumps({"persons": [{"box_2d": [0, 0, 1000], "garments": []}]}),
    json.dumps({"persons": [{"box_2d": [0, 0, 1000, 1000], "garments": []}, None]}),
    json.dumps({"persons": [{"box_2d": [0, 0, 1000, 1000]}]}),
    json.dumps({"persons": [{"box_2d": [0, 0, 1000, 1000], "garments": "bad"}]}),
    json.dumps(
        {
            "persons": [
                {
                    "box_2d": [0, 0, 1000, 1000],
                    "garments": [{"category": "hat", "box_2d": [1, 1, 2, 2]}],
                }
            ]
        }
    ),
    json.dumps(
        {
            "persons": [
                {
                    "box_2d": [1, 2, 3, 4],
                    "garments": [
                        {"category": "outer", "box_2d": [0, 0, 1, 1]},
                        {"category": "outer", "box_2d": [0, 0, 1, 1]},
                    ],
                }
            ]
        }
    ),
    json.dumps(
        {
            "persons": [
                {
                    "box_2d": [0, 0, 1000, 1000],
                    "garments": [valid_person() for _ in range(9)],
                }
            ]
        }
    ),
    json.dumps({"persons": [valid_person(), valid_person()]}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", INVALID_OUTPUTS)
async def test_any_invalid_model_output_requires_manual_selection(text) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.post(ENDPOINT).mock(return_value=httpx.Response(200, json=envelope(text)))
        result = await GeminiDetectionProvider("test").detect(FRAME)
    assert result["persons"] == []
    assert result["manual_selection_required"] is True
    DETECTION_VALIDATOR.validate(result)
    assert semantic_check(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": []},
        {
            "candidates": [
                {"finishReason": "SAFETY", "content": {"parts": [{"text": "{}"}]}}
            ]
        },
        {
            "candidates": [
                {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}
            ]
        },
        envelope(""),
    ],
)
async def test_blocked_empty_and_nonstop_responses_return_manual(response) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.post(ENDPOINT).mock(return_value=httpx.Response(200, json=response))
        result = await GeminiDetectionProvider("test").detect(FRAME)
    assert result["persons"] == []
    assert result["manual_selection_required"] is True
    DETECTION_VALIDATOR.validate(result)
    assert semantic_check(result)


@pytest.mark.asyncio
async def test_thought_parts_are_ignored_when_joining_output_text() -> None:
    valid_text = json.dumps({"persons": [valid_person()]})
    response = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"thought": True, "text": "not valid JSON"},
                        {"text": valid_text},
                    ]
                },
            }
        ]
    }
    with respx.mock(assert_all_called=True) as mock:
        mock.post(ENDPOINT).mock(return_value=httpx.Response(200, json=response))
        result = await GeminiDetectionProvider("test").detect(FRAME)
    assert result["manual_selection_required"] is False
    assert semantic_check(result)
    DETECTION_VALIDATOR.validate(result)


@pytest.mark.asyncio
async def test_candidate_without_candidates_list_is_retryable_unavailable() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.post(ENDPOINT).mock(
            return_value=httpx.Response(200, json={"usageMetadata": {}})
        )
        with pytest.raises(DetectionUnavailable) as caught:
            await GeminiDetectionProvider("test").detect(FRAME)
    assert caught.value.safe_code == "analysis_unavailable"
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_oversized_frame_rejected_without_request() -> None:
    frame = PreparedImage(b"x" * (15 * 1024 * 1024 + 1), "image/jpeg", 1, 1)
    with respx.mock(assert_all_called=False) as mock:
        with pytest.raises(DetectionUnavailable) as caught:
            await GeminiDetectionProvider("test").detect(frame)
        assert mock.calls.call_count == 0
    assert caught.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "retryable"),
    [(400, False), (401, False), (403, False), (429, True), (500, True), (503, True)],
)
async def test_http_errors_have_safe_retry_classification(status, retryable) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.post(ENDPOINT).mock(return_value=httpx.Response(status))
        with pytest.raises(DetectionUnavailable) as caught:
            await GeminiDetectionProvider("test").detect(FRAME)
    assert caught.value.retryable is retryable


@pytest.mark.asyncio
async def test_transport_error_is_retryable_and_missing_envelope_is_retryable() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ENDPOINT).mock(side_effect=httpx.ReadTimeout("timeout"))
        with pytest.raises(DetectionUnavailable) as caught:
            await GeminiDetectionProvider("test").detect(FRAME)
    assert caught.value.retryable is True
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ENDPOINT).mock(return_value=httpx.Response(200, content=b"bad json"))
        with pytest.raises(DetectionUnavailable) as caught:
            await GeminiDetectionProvider("test").detect(FRAME)
    assert caught.value.retryable is True


def test_semantic_checker_rejects_every_contract_semantic_invalid_fixture() -> None:
    for path in (CONTRACTS / "fixtures" / "semantic_invalid").glob("*.json"):
        fixture = json.loads(path.read_text())
        DETECTION_VALIDATOR.validate(fixture)
        assert not semantic_check(fixture), path.name


@pytest.mark.asyncio
async def test_logging_omits_key_and_model_text(caplog) -> None:
    caplog.set_level(logging.INFO, logger="drippop.providers.gemini")
    secret_text = "sentinel-private-model-text"
    with respx.mock(assert_all_called=True) as mock:
        mock.post(ENDPOINT).mock(
            return_value=httpx.Response(200, json=envelope(secret_text))
        )
        provider = GeminiDetectionProvider("sentinel-key")
        try:
            result = await provider.detect(FRAME)
        finally:
            await provider.client.aclose()
    DETECTION_VALIDATOR.validate(result)
    assert semantic_check(result)
    assert secret_text not in caplog.text
    assert FRAME.data.decode() not in caplog.text
    assert "sentinel-key" not in caplog.text
