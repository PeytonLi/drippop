import json
import math
from pathlib import Path
from typing import Any, TypedDict

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


class GarmentDetection(TypedDict):
    id: str
    category: str
    box: list[float]


class PersonDetection(TypedDict):
    id: str
    box: list[float]
    garments: list[GarmentDetection]


class DetectionResponse(TypedDict):
    image_width: int
    image_height: int
    coordinate_space: str
    persons: list[PersonDetection]
    manual_selection_required: bool


class ContractSchemas:
    def __init__(self, contracts_dir: Path) -> None:
        self.dir = contracts_dir
        self.schemas: dict[str, dict[str, Any]] = {
            p.name: json.loads(p.read_text()) for p in (contracts_dir / "schemas").glob("*.json")
        }
        resources = [(s["$id"], Resource.from_contents(s)) for s in self.schemas.values()] + [
            (name, Resource.from_contents(s)) for name, s in self.schemas.items()
        ]
        self.registry: Registry[Any] = Registry().with_resources(resources)
        self.categories: dict[str, Any] = json.loads(
            (contracts_dir / "config" / "categories.json").read_text()
        )

    def validator(self, schema_name: str) -> Draft202012Validator:
        return Draft202012Validator(self.schemas[schema_name], registry=self.registry)

    def is_valid(self, schema_name: str, doc: Any) -> bool:
        return not list(self.validator(schema_name).iter_errors(doc))


def _box_ok(box: Any) -> bool:
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box)
    ):
        return False
    left, top, right, bottom = box
    return all(math.isfinite(v) for v in box) and left < right and top < bottom


def detection_semantics_ok(doc: Any) -> bool:
    persons = doc.get("persons")
    if not isinstance(persons, list):
        return False
    person_ids: set[str] = set()
    garment_ids: set[str] = set()
    for person in persons:
        if not isinstance(person, dict):
            return False
        pid = person.get("id")
        if not isinstance(pid, str) or pid in person_ids:
            return False
        person_ids.add(pid)
        if not _box_ok(person.get("box")):
            return False
        garments = person.get("garments")
        if not isinstance(garments, list):
            return False
        for garment in garments:
            if not isinstance(garment, dict):
                return False
            gid = garment.get("id")
            if not isinstance(gid, str) or gid in garment_ids:
                return False
            garment_ids.add(gid)
            if not _box_ok(garment.get("box")):
                return False
    if not persons and doc.get("manual_selection_required") is not True:
        return False
    return True


def validate_detection(schemas: ContractSchemas, doc: Any) -> bool:
    return schemas.is_valid("detection_response.schema.json", doc) and detection_semantics_ok(doc)
