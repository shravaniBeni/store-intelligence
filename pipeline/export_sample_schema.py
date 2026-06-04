from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.models import StoreEvent


EVENT_TYPE_MAP = {
    "ENTRY": "entry",
    "EXIT": "exit",
    "ZONE_ENTER": "zone_entered",
    "ZONE_EXIT": "zone_exited",
    "BILLING_QUEUE_JOIN": "queue_joined",
    "BILLING_QUEUE_ABANDON": "queue_abandoned",
    "REENTRY": "reentry",
    "ZONE_DWELL": "zone_dwell",
}


def to_sample_schema(record: dict[str, Any]) -> dict[str, Any]:
    event = StoreEvent.model_validate(record)
    metadata = event.metadata
    output: dict[str, Any] = {
        "event_id": str(event.event_id),
        "event_type": EVENT_TYPE_MAP[event.event_type.value],
        "id_token": event.visitor_id,
        "store_id": event.store_id,
        "store_code": event.store_id,
        "camera_id": event.camera_id,
        "event_timestamp": event.timestamp.isoformat().replace("+00:00", "Z"),
        "is_staff": event.is_staff,
        "confidence": event.confidence,
    }
    if event.zone_id:
        output["zone_id"] = event.zone_id
    if metadata.sku_zone:
        output["zone_name"] = metadata.sku_zone
    if metadata.queue_depth is not None:
        output["queue_depth"] = metadata.queue_depth
    if metadata.session_seq is not None:
        output["session_seq"] = metadata.session_seq
    if event.dwell_ms:
        output["dwell_ms"] = event.dwell_ms
    if event.event_type.value in {"BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "ZONE_DWELL"} and event.dwell_ms:
        output["wait_seconds"] = round(event.dwell_ms / 1000, 3)
    return output


def export_jsonl(input_path: Path, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with input_path.open("r", encoding="utf-8") as source, output_path.open("w", encoding="utf-8") as output:
        for line in source:
            if not line.strip():
                continue
            output.write(json.dumps(to_sample_schema(json.loads(line)), separators=(",", ":")) + "\n")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    count = export_jsonl(args.input, args.output)
    print(f"wrote {count} sample-schema events to {args.output}")


if __name__ == "__main__":
    main()
