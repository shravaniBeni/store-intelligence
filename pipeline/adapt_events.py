from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import StoreEvent


EVENT_TYPE_MAP = {
    "entry": "ENTRY",
    "exit": "EXIT",
    "zone_entered": "ZONE_ENTER",
    "zone_exited": "ZONE_EXIT",
    "queue_joined": "BILLING_QUEUE_JOIN",
    "queue_entered": "BILLING_QUEUE_JOIN",
    "queue_abandoned": "BILLING_QUEUE_ABANDON",
    "queue_completed": "BILLING_QUEUE_JOIN",
}

MAPPED_SOURCE_KEYS = {
    "event_id",
    "event_type",
    "id_token",
    "track_id",
    "store_code",
    "store_id",
    "camera_id",
    "event_timestamp",
    "event_time",
    "queue_join_ts",
    "timestamp",
    "zone_id",
    "zone_name",
    "wait_seconds",
    "dwell_ms",
    "is_staff",
    "confidence",
    "metadata",
    "queue_depth",
    "session_seq",
}


def is_canonical_event(record: dict[str, Any]) -> bool:
    try:
        StoreEvent.model_validate(record)
    except Exception:
        return False
    return True


def adapt_record(record: dict[str, Any], line_number: int) -> dict[str, Any] | None:
    if is_canonical_event(record):
        return record

    event_type = EVENT_TYPE_MAP.get(str(record.get("event_type", "")).lower())
    visitor_id = record.get("id_token") or record.get("track_id")
    store_id = record.get("store_code") or record.get("store_id")
    timestamp = first_present(record, ["event_timestamp", "event_time", "queue_join_ts", "timestamp"])
    if not event_type or visitor_id is None or not store_id or not timestamp:
        print(f"Skipping unsafe organizer event at line {line_number}: cannot infer canonical fields")
        return None

    metadata = dict(record.get("metadata") or {})
    metadata.setdefault("queue_depth", record.get("queue_depth"))
    metadata.setdefault("sku_zone", record.get("zone_name") or record.get("zone_id"))
    metadata.setdefault("session_seq", record.get("session_seq") or line_number)
    raw_source = {key: value for key, value in record.items() if key not in MAPPED_SOURCE_KEYS}
    if raw_source:
        metadata["raw_source"] = raw_source

    adapted = {
        "event_id": record.get("event_id") or str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": record.get("camera_id") or "UNKNOWN_CAMERA",
        "visitor_id": str(visitor_id),
        "event_type": event_type,
        "timestamp": normalize_timestamp(str(timestamp)),
        "zone_id": record.get("zone_id"),
        "dwell_ms": dwell_ms(record),
        "is_staff": bool(record.get("is_staff", False)),
        "confidence": float(record.get("confidence", 1.0)),
        "metadata": metadata,
    }
    StoreEvent.model_validate(adapted)
    return adapted


def first_present(record: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if record.get(key):
            return record[key]
    return None


def normalize_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def dwell_ms(record: dict[str, Any]) -> int:
    if record.get("wait_seconds") is not None:
        return int(float(record["wait_seconds"]) * 1000)
    return int(record.get("dwell_ms") or 0)


def adapt_jsonl(input_path: Path, output_path: Path) -> int:
    accepted = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("r", encoding="utf-8") as source, output_path.open("w", encoding="utf-8") as output:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            adapted = adapt_record(json.loads(line), line_number)
            if adapted is None:
                continue
            output.write(json.dumps(adapted, separators=(",", ":")) + "\n")
            accepted += 1
    return accepted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    count = adapt_jsonl(args.input, args.output)
    print(f"wrote {count} canonical events to {args.output}")


if __name__ == "__main__":
    main()
