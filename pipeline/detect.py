from __future__ import annotations

import argparse
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from pipeline.config import START_TIME_BY_CAMERA, STORE_ID, CameraConfig, default_camera_config_path, load_camera_config
from pipeline.emit import make_event, write_jsonl


PERSON_CLASS_ID = 0


def camera_id_from_path(path: Path) -> str:
    return path.stem.upper().replace(" ", "_")


def normalize_camera_name(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def camera_alias_map(cameras: dict[str, CameraConfig]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for camera_id, config in cameras.items():
        aliases[normalize_camera_name(camera_id)] = camera_id
        aliases[normalize_camera_name(camera_id.replace("_", " "))] = camera_id
        for alias in config.aliases:
            aliases[normalize_camera_name(alias)] = camera_id
    return aliases


def canonical_camera_id_for_path(path: Path, aliases: dict[str, str]) -> str | None:
    candidates = [
        normalize_camera_name(path.stem),
        normalize_camera_name(camera_id_from_path(path)),
    ]
    for candidate in candidates:
        if candidate in aliases:
            return aliases[candidate]
    return None


def discover_clips(clips_root: Path) -> list[Path]:
    return sorted(clips_root.rglob("*.mp4"))


def in_box(point: tuple[float, float], box: tuple[int, int, int, int]) -> bool:
    x, y = point
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def dominant_zone(config: CameraConfig, center: tuple[float, float]) -> str | None:
    for zone, box in config.zones.items():
        if in_box(center, box):
            return "BILLING" if zone == "CASH_COUNTER" else zone
    return None


def is_probable_staff(config: CameraConfig, zone_id: str | None, seconds_seen: float, center: tuple[float, float]) -> tuple[bool, str | None]:
    if config.exclude_from_customer_metrics:
        return True, f"{config.role} camera excluded from customer metrics"
    if config.role == "billing" and seconds_seen > 45:
        return True, "long-running billing-side presence"
    if config.role == "billing" and zone_id == "BILLING" and center[0] > 650:
        return True, "behind cash counter ROI"
    return False, None


class SessionLinker:
    def __init__(self) -> None:
        self.track_to_visitor: dict[str, str] = {}
        self.exited: list[tuple[datetime, str, tuple[float, float]]] = []
        self.next_id = 1
        self.min_reentry_gap = timedelta(seconds=60)
        self.max_reentry_gap = timedelta(minutes=3)

    def visitor_for(self, camera_id: str, track_id: int, timestamp: datetime, center: tuple[float, float]) -> tuple[str, bool]:
        key = f"{camera_id}:{track_id}"
        if key in self.track_to_visitor:
            return self.track_to_visitor[key], False
        for exit_time, visitor_id, exit_center in reversed(self.exited[-20:]):
            gap = timestamp - exit_time
            if self.min_reentry_gap <= gap <= self.max_reentry_gap and distance(center, exit_center) < 280:
                self.track_to_visitor[key] = visitor_id
                return visitor_id, True
        visitor_id = f"VIS_{self.next_id:06d}"
        self.next_id += 1
        self.track_to_visitor[key] = visitor_id
        return visitor_id, False

    def mark_exit(self, timestamp: datetime, visitor_id: str, center: tuple[float, float]) -> None:
        self.exited.append((timestamp, visitor_id, center))


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def threshold_event_type(config: CameraConfig, direction: str) -> str:
    inbound = config.inbound_crossing_direction
    return "ENTRY" if direction == inbound else "EXIT"


def first_threshold_event_type(config: CameraConfig, center: tuple[float, float]) -> str:
    if config.entry_line_y is None:
        return "ENTRY"
    if config.inbound_crossing_direction == "down":
        return "ENTRY" if center[1] >= config.entry_line_y else "EXIT"
    return "ENTRY" if center[1] < config.entry_line_y else "EXIT"


def run_yolo_bytetrack(
    clips: Iterable[Path],
    output: Path,
    model_name: str,
    frame_stride: int,
    max_frames: int | None,
    camera_config_path: Path,
) -> list[dict]:
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("ultralytics is required for YOLOv8n + ByteTrack detection") from exc

    model = YOLO(model_name)
    cameras = load_camera_config(camera_config_path)
    aliases = camera_alias_map(cameras)
    billing_camera_ids = {camera_id for camera_id, config in cameras.items() if config.role == "billing"}
    linker = SessionLinker()
    events: list[dict] = []
    track_state: dict[str, dict] = {}

    for clip in clips:
        camera_id = canonical_camera_id_for_path(clip, aliases)
        if camera_id is None or camera_id not in cameras:
            print(f"Skipping unmapped camera clip: {clip}")
            continue
        config = cameras[camera_id]
        start = datetime.fromisoformat(START_TIME_BY_CAMERA[camera_id])
        frame_index = -1
        results = model.track(
            source=str(clip),
            tracker="bytetrack.yaml",
            classes=[PERSON_CLASS_ID],
            conf=0.2,
            iou=0.5,
            stream=True,
            persist=True,
            vid_stride=frame_stride,
            verbose=False,
        )
        for result in results:
            frame_index += frame_stride
            if max_frames and frame_index > max_frames:
                break
            fps = getattr(result, "fps", None) or 25
            timestamp = start + timedelta(seconds=frame_index / fps)
            boxes = result.boxes
            if boxes is None or boxes.id is None:
                continue
            for xyxy, track_id, conf in zip(boxes.xyxy.tolist(), boxes.id.tolist(), boxes.conf.tolist()):
                x1, y1, x2, y2 = xyxy
                center = ((x1 + x2) / 2, (y1 + y2) / 2)
                zone_id = dominant_zone(config, center)
                visitor_id, is_reentry = linker.visitor_for(camera_id, int(track_id), timestamp, center)
                key = f"{camera_id}:{int(track_id)}"
                state = track_state.setdefault(
                    key,
                    {
                        "zone": None,
                        "first_seen": timestamp,
                        "last_center": center,
                        "seen_frames": 0,
                        "seq": 0,
                        "entry_emitted": False,
                    },
                )
                state["seen_frames"] += 1
                seconds_seen = (timestamp - state["first_seen"]).total_seconds()
                is_staff, staff_reason = is_probable_staff(config, zone_id, seconds_seen, center)
                metadata = {
                    "source_track_id": key,
                    "session_seq": state["seq"] + 1,
                    "staff_reason": staff_reason,
                }
                if is_reentry:
                    events.append(make_event(store_id=STORE_ID, camera_id=camera_id, visitor_id=visitor_id, event_type="REENTRY", timestamp=timestamp, zone_id=None, is_staff=is_staff, confidence=conf, metadata={**metadata, "reid_reason": "heuristic recent-exit match; not guaranteed identity"}))
                if config.role == "entry_exit" and config.entry_line_y is not None:
                    previous = state["last_center"]
                    if not state["entry_emitted"] and previous[1] >= config.entry_line_y > center[1]:
                        event_type = threshold_event_type(config, "up")
                        events.append(make_event(store_id=STORE_ID, camera_id=camera_id, visitor_id=visitor_id, event_type=event_type, timestamp=timestamp, zone_id=None, is_staff=is_staff, confidence=conf, metadata={**metadata, "direction_reason": "tracked threshold crossing: up"}))
                        state["entry_emitted"] = True
                        if event_type == "EXIT":
                            linker.mark_exit(timestamp, visitor_id, center)
                    elif not state["entry_emitted"] and previous[1] < config.entry_line_y <= center[1]:
                        event_type = threshold_event_type(config, "down")
                        events.append(make_event(store_id=STORE_ID, camera_id=camera_id, visitor_id=visitor_id, event_type=event_type, timestamp=timestamp, zone_id=None, is_staff=is_staff, confidence=conf, metadata={**metadata, "direction_reason": "tracked threshold crossing: down"}))
                        if event_type == "EXIT":
                            linker.mark_exit(timestamp, visitor_id, center)
                        state["entry_emitted"] = True
                if zone_id and zone_id != state["zone"]:
                    if (
                        config.role == "entry_exit"
                        and zone_id == "ENTRY_THRESHOLD"
                        and config.entry_line_y is not None
                        and not state["entry_emitted"]
                    ):
                        threshold_type = first_threshold_event_type(config, center)
                        threshold_metadata = {
                            **metadata,
                            "direction_reason": "first threshold observation classified by configured entry line side",
                        }
                        events.append(make_event(store_id=STORE_ID, camera_id=camera_id, visitor_id=visitor_id, event_type=threshold_type, timestamp=timestamp, zone_id=None, is_staff=is_staff, confidence=conf, metadata=threshold_metadata))
                        state["entry_emitted"] = True
                        if threshold_type == "EXIT":
                            linker.mark_exit(timestamp, visitor_id, center)
                    if state["zone"]:
                        events.append(make_event(store_id=STORE_ID, camera_id=camera_id, visitor_id=visitor_id, event_type="ZONE_EXIT", timestamp=timestamp, zone_id=state["zone"], is_staff=is_staff, confidence=conf, metadata=metadata))
                    events.append(make_event(store_id=STORE_ID, camera_id=camera_id, visitor_id=visitor_id, event_type="ZONE_ENTER", timestamp=timestamp, zone_id=zone_id, is_staff=is_staff, confidence=conf, metadata=metadata))
                    if zone_id == "BILLING":
                        depth = billing_depth(track_state, billing_camera_ids)
                        events.append(make_event(store_id=STORE_ID, camera_id=camera_id, visitor_id=visitor_id, event_type="BILLING_QUEUE_JOIN", timestamp=timestamp, zone_id="BILLING", is_staff=is_staff, confidence=conf, metadata={**metadata, "queue_depth": depth}))
                    state["zone"] = zone_id
                    state["zone_entered_at"] = timestamp
                if zone_id and state.get("zone_entered_at"):
                    dwell = (timestamp - state["zone_entered_at"]).total_seconds()
                    if dwell >= 30 and int(dwell) % 30 < max(1, frame_stride // 10):
                        events.append(make_event(store_id=STORE_ID, camera_id=camera_id, visitor_id=visitor_id, event_type="ZONE_DWELL", timestamp=timestamp, zone_id=zone_id, dwell_ms=int(dwell * 1000), is_staff=is_staff, confidence=conf, metadata=metadata))
                state["last_center"] = center
                state["seq"] += 1
    write_jsonl(events, output)
    return events


def billing_depth(track_state: dict[str, dict], billing_camera_ids: set[str]) -> int:
    active = 0
    for key, state in track_state.items():
        camera_id = key.split(":", 1)[0]
        if camera_id in billing_camera_ids and state.get("zone") == "BILLING":
            active += 1
    return active


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=Path, default=Path("data/raw"))
    parser.add_argument("--output", type=Path, default=Path("data/events.jsonl"))
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--camera-config", type=Path, default=default_camera_config_path())
    args = parser.parse_args()
    clips = discover_clips(args.clips)
    events = run_yolo_bytetrack(clips, args.output, args.model, args.frame_stride, args.max_frames, args.camera_config)
    print(f"wrote {len(events)} events to {args.output}")


if __name__ == "__main__":
    main()
