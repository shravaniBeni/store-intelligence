# PROMPT: Add focused tests for pipeline coverage without changing production behavior: detection helper functions with mocked YOLO/ByteTrack, event emission, POS normalization, and replay HTTP posting.
# CHANGES MADE: Used temp files, monkeypatching, and fake tracker outputs so tests cover pipeline logic deterministically without running model inference or making network calls.

from __future__ import annotations

import csv
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import StoreEvent
from pipeline.config import CameraConfig
from pipeline.detect import (
    SessionLinker,
    billing_depth,
    camera_id_from_path,
    distance,
    dominant_zone,
    first_threshold_event_type,
    in_box,
    is_probable_staff,
    run_yolo_bytetrack,
    threshold_event_type,
)
from pipeline.emit import make_event, write_jsonl
from pipeline.prepare_pos import normalize_pos
from pipeline.replay import post_batch, replay


class _ListLike:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return self._values


class _Boxes:
    def __init__(self, rows):
        self.xyxy = _ListLike([row["xyxy"] for row in rows])
        self.id = _ListLike([row["id"] for row in rows])
        self.conf = _ListLike([row["conf"] for row in rows])


class _Result:
    def __init__(self, rows, fps=25):
        self.boxes = _Boxes(rows) if rows is not None else None
        self.fps = fps


def test_detection_helper_functions_and_session_linking():
    entry = CameraConfig(
        camera_id="CAM_3",
        role="entry_exit",
        zones={"ENTRY_THRESHOLD": (0, 0, 100, 100)},
        entry_line_y=50,
        inbound_crossing_direction="down",
    )
    billing = CameraConfig(
        camera_id="CAM_5",
        role="billing",
        zones={"BILLING": (0, 0, 100, 100), "CASH_COUNTER": (60, 0, 100, 100)},
    )
    backroom = CameraConfig(
        camera_id="CAM_4",
        role="backroom_storage",
        zones={"BACKROOM": (0, 0, 100, 100)},
        exclude_from_customer_metrics=True,
    )

    assert camera_id_from_path(Path("CAM 3.mp4")) == "CAM_3"
    assert in_box((50, 50), (0, 0, 100, 100))
    assert not in_box((101, 50), (0, 0, 100, 100))
    assert dominant_zone(billing, (70, 20)) == "BILLING"
    assert dominant_zone(entry, (200, 200)) is None
    assert threshold_event_type(entry, "down") == "ENTRY"
    assert threshold_event_type(entry, "up") == "EXIT"
    assert first_threshold_event_type(entry, (10, 60)) == "ENTRY"
    assert first_threshold_event_type(entry, (10, 40)) == "EXIT"
    assert is_probable_staff(backroom, "BACKROOM", 1, (20, 20))[0] is True
    assert is_probable_staff(billing, "BILLING", 46, (20, 20))[0] is True
    assert is_probable_staff(billing, "BILLING", 1, (700, 20))[0] is True
    assert is_probable_staff(entry, None, 1, (20, 20)) == (False, None)
    assert distance((0, 0), (3, 4)) == 5

    linker = SessionLinker()
    now = datetime(2026, 4, 10, tzinfo=timezone.utc)
    first_visitor, first_reentry = linker.visitor_for("CAM_3", 1, now, (10, 10))
    assert first_visitor == "VIS_000001"
    assert first_reentry is False
    assert linker.visitor_for("CAM_3", 1, now, (10, 10)) == (first_visitor, False)
    linker.mark_exit(now, first_visitor, (10, 10))
    too_soon = linker.visitor_for("CAM_3", 2, now + timedelta(seconds=10), (12, 12))
    assert too_soon[1] is False
    reentry = linker.visitor_for("CAM_3", 3, now + timedelta(seconds=75), (12, 12))
    assert reentry == (first_visitor, True)


def test_event_emission_and_jsonl_roundtrip(tmp_path):
    event = make_event(
        store_id="ST1008",
        camera_id="CAM_1",
        visitor_id="VIS_TEST",
        event_type="ZONE_DWELL",
        timestamp=datetime(2026, 4, 10, 12, tzinfo=timezone.utc),
        zone_id="SKINCARE_WALL",
        dwell_ms=30000,
        confidence=0.812345,
        metadata={"session_seq": 7, "source_track_id": "CAM_1:1"},
    )
    assert event["confidence"] == 0.8123
    assert event["metadata"]["queue_depth"] is None
    assert event["metadata"]["sku_zone"] == "SKINCARE_WALL"
    StoreEvent.model_validate(event)

    output = tmp_path / "events.jsonl"
    write_jsonl([event], output)
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["event_id"] == event["event_id"]


def test_pos_normalization_aggregates_invoice_lines(tmp_path):
    source = tmp_path / "raw_pos.csv"
    source.write_text(
        "\n".join(
            [
                "invoice_number,order_date,order_time,store_id,total_amount",
                "INV1,10-04-2026,12:01:02,ST1008,100.25",
                "INV1,10-04-2026,12:01:02,ST1008,50.75",
                "INV2,10-04-2026,12:05:00,ST1008,",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "normalized" / "pos.csv"
    assert normalize_pos(source, output) == 2
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert rows[0] == {
        "store_id": "ST1008",
        "transaction_id": "INV1",
        "timestamp": "2026-04-10T12:01:02Z",
        "basket_value_inr": "151.00",
    }
    assert rows[1]["basket_value_inr"] == "0.00"


def test_replay_posts_batches_and_skips_blank_lines(tmp_path, monkeypatch):
    events = [
        make_event(
            store_id="ST1008",
            camera_id="CAM_1",
            visitor_id=f"VIS_{idx}",
            event_type="ZONE_ENTER",
            timestamp=datetime(2026, 4, 10, 12, idx, tzinfo=timezone.utc),
            zone_id="MAKEUP_WALL",
        )
        for idx in range(3)
    ]
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps(events[0]) + "\n\n" + json.dumps(events[1]) + "\n" + json.dumps(events[2]) + "\n",
        encoding="utf-8",
    )
    posts = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"accepted": 1}'

    def fake_urlopen(req, timeout):
        posts.append((req.full_url, json.loads(req.data.decode("utf-8")), timeout))
        return _Response()

    monkeypatch.setattr("pipeline.replay.request.urlopen", fake_urlopen)
    monkeypatch.setattr("pipeline.replay.time.sleep", lambda _: None)

    replay(events_path, "http://example.test/", batch_size=2, delay=0.01)
    assert [len(post[1]["events"]) for post in posts] == [2, 1]
    assert posts[0][0] == "http://example.test/events/ingest"
    assert posts[0][2] == 15

    post_batch("http://example.test", [events[0]])
    assert posts[-1][0] == "http://example.test/events/ingest"


def test_run_yolo_bytetrack_with_mocked_tracker(tmp_path, monkeypatch):
    camera_config = tmp_path / "camera_config.json"
    camera_config.write_text(
        json.dumps(
            {
                "cameras": {
                    "CAM_3": {
                        "role": "entry_exit",
                        "entry_line_y": 50,
                        "inbound_crossing_direction": "down",
                        "zones": {"ENTRY_THRESHOLD": [0, 0, 100, 100]},
                    },
                    "CAM_5": {
                        "role": "billing",
                        "zones": {"BILLING": [0, 0, 100, 100]},
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    class FakeYOLO:
        def __init__(self, model_name):
            self.model_name = model_name

        def track(self, source, **kwargs):
            assert kwargs["tracker"] == "bytetrack.yaml"
            assert kwargs["classes"] == [0]
            if "CAM 3" in source:
                return iter(
                    [
                        _Result(
                            [
                                {"xyxy": [10, 10, 30, 30], "id": 1, "conf": 0.8},
                                {"xyxy": [40, 70, 60, 90], "id": 3, "conf": 0.85},
                            ]
                        ),
                        _Result(
                            [
                                {"xyxy": [10, 70, 30, 90], "id": 1, "conf": 0.9},
                                {"xyxy": [40, 70, 60, 90], "id": 3, "conf": 0.86},
                            ]
                        ),
                        _Result(None),
                    ]
                )
            return iter(
                [
                    _Result([{"xyxy": [10, 10, 30, 30], "id": 2, "conf": 0.7}]),
                    _Result([{"xyxy": [10, 10, 30, 30], "id": 2, "conf": 0.75}]),
                ]
            )

    fake_ultralytics = types.ModuleType("ultralytics")
    fake_ultralytics.YOLO = FakeYOLO
    monkeypatch.setitem(sys.modules, "ultralytics", fake_ultralytics)

    output = tmp_path / "events.jsonl"
    events = run_yolo_bytetrack(
        [Path("CAM 3.mp4"), Path("CAM 5.mp4"), Path("CAM 9.mp4")],
        output,
        "fake-model.pt",
        frame_stride=1000,
        max_frames=None,
        camera_config_path=camera_config,
    )
    event_types = [event["event_type"] for event in events]
    assert "EXIT" in event_types
    assert "ENTRY" in event_types
    assert "ZONE_ENTER" in event_types
    assert "BILLING_QUEUE_JOIN" in event_types
    assert "ZONE_DWELL" in event_types
    assert billing_depth({"CAM_5:2": {"zone": "BILLING"}, "CAM_3:1": {"zone": "BILLING"}}, {"CAM_5"}) == 1
    assert output.exists()
    for event in events:
        StoreEvent.model_validate(event)
