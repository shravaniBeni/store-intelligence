from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path


def make_event(
    *,
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp: datetime,
    zone_id: str | None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.75,
    metadata: dict | None = None,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": round(float(confidence), 4),
        "metadata": {
            "queue_depth": None,
            "sku_zone": zone_id,
            "session_seq": 1,
            **(metadata or {}),
        },
    }


def write_jsonl(events: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")

