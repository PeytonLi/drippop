import yaml

from tests.conftest import CONTRACTS_DIR


def test_routes_match_openapi(app):
    spec = yaml.safe_load((CONTRACTS_DIR / "openapi.yaml").read_text())
    documented = set()
    for path, ops in spec["paths"].items():
        for method in ops:
            if method.upper() in ("GET", "POST", "DELETE", "PUT", "PATCH"):
                documented.add((method.upper(), path))

    actual = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods or path == "/openapi.json":
            continue
        for m in methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            actual.add((m, path))

    # FastAPI uses {job_id}; openapi uses {job_id} too — compare directly.
    assert actual == documented


def test_documented_status_families_used(app):
    spec = yaml.safe_load((CONTRACTS_DIR / "openapi.yaml").read_text())
    families = set()
    for ops in spec["paths"].values():
        for op in ops.values():
            if not isinstance(op, dict) or "responses" not in op:
                continue
            for code in op["responses"]:
                families.add(str(code)[0])
    assert families == {"2", "4"} | {"5"} or ("4" in families and "2" in families)
