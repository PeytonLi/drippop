import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                if key == "owner_uid" and isinstance(value, str):
                    payload["owner_uid_hash"] = hashlib.sha256(value.encode()).hexdigest()[:12]
                else:
                    payload[key] = value
        if record.exc_info:
            payload["exception"] = record.exc_info[1].__class__.__name__
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def log(event: str, level: int = logging.INFO, **fields: Any) -> None:
    logging.getLogger("drippop").log(level, event, extra={"fields": fields})
