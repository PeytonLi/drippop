"""Validates contract fixtures against the JSON Schemas. Run: uv run --with jsonschema --with referencing pytest contracts/tests"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {p.name: json.loads(p.read_text()) for p in (ROOT / "schemas").glob("*.json")}
REGISTRY = Registry().with_resources(
    [(s["$id"], Resource.from_contents(s)) for s in SCHEMAS.values()]
    + [(name, Resource.from_contents(s)) for name, s in SCHEMAS.items()]
)


def validator_for(fixture: Path) -> Draft202012Validator:
    kind = fixture.name.split(".")[0]
    return Draft202012Validator(SCHEMAS[f"{kind}.schema.json"], registry=REGISTRY)


def fixtures(sub: str):
    return sorted((ROOT / "fixtures" / sub).glob("*.json"))


@pytest.mark.parametrize("fixture", fixtures("valid"), ids=lambda p: p.name)
def test_valid(fixture):
    validator_for(fixture).validate(json.loads(fixture.read_text()))


@pytest.mark.parametrize("fixture", fixtures("invalid"), ids=lambda p: p.name)
def test_invalid(fixture):
    assert list(validator_for(fixture).iter_errors(json.loads(fixture.read_text())))


@pytest.mark.parametrize("fixture", fixtures("semantic_invalid"), ids=lambda p: p.name)
def test_semantic_invalid_is_schema_valid(fixture):
    # These pass the schema but MUST be rejected by consumer semantic checks (D-004).
    validator_for(fixture).validate(json.loads(fixture.read_text()))


def test_schemas_are_valid():
    for s in SCHEMAS.values():
        Draft202012Validator.check_schema(s)
