from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


STORE_ID = "ST1008"
STORE_NAME = "Brigade_Bangalore"
BUSINESS_DATE = "2026-04-10"
START_TIME_BY_CAMERA = {
    "CAM_1": "2026-04-10T20:10:28+00:00",
    "CAM_2": "2026-04-10T20:10:03+00:00",
    "CAM_3": "2026-04-10T20:10:18+00:00",
    "CAM_4": "2026-04-10T20:09:46+00:00",
    "CAM_5": "2026-04-10T20:09:48+00:00",
}


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    role: str
    zones: dict[str, tuple[int, int, int, int]]
    entry_line_y: int | None = None
    inbound_crossing_direction: str = "down"
    exclude_from_customer_metrics: bool = False
    mapping_basis: str | None = None


def load_camera_config(path: Path) -> dict[str, CameraConfig]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cameras: dict[str, CameraConfig] = {}
    for camera_id, item in raw["cameras"].items():
        cameras[camera_id] = CameraConfig(
            camera_id=camera_id,
            role=item["role"],
            zones={name: tuple(box) for name, box in item.get("zones", {}).items()},
            entry_line_y=item.get("entry_line_y"),
            inbound_crossing_direction=item.get("inbound_crossing_direction", "down"),
            exclude_from_customer_metrics=item.get("exclude_from_customer_metrics", False),
            mapping_basis=item.get("mapping_basis"),
        )
    return cameras


def default_camera_config_path() -> Path:
    return Path("data/camera_config.json")
