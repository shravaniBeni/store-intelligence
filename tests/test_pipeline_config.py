# PROMPT: Generate pipeline tests that validate generated Store Intelligence events and the configurable camera-role mapping.
# CHANGES MADE: Avoided model execution in unit tests; this file checks schema compliance and config-driven camera role behavior instead.

from __future__ import annotations

from datetime import datetime, timezone

from app.models import StoreEvent
from pipeline.config import default_camera_config_path, load_camera_config
from pipeline.emit import make_event


def test_camera_roles_are_loaded_from_json_config():
    cameras = load_camera_config(default_camera_config_path())
    assert "CAM_3" in cameras
    assert cameras["CAM_3"].role == "entry_exit"
    assert cameras["CAM_3"].mapping_basis
    assert cameras["CAM_4"].exclude_from_customer_metrics is True


def test_generated_event_matches_required_schema():
    event = make_event(
        store_id="ST1008",
        camera_id="CAM_3",
        visitor_id="VIS_000001",
        event_type="ENTRY",
        timestamp=datetime(2026, 4, 10, 20, 10, tzinfo=timezone.utc),
        zone_id=None,
        confidence=0.44,
        metadata={"source_track_id": "CAM_3:7"},
    )
    parsed = StoreEvent.model_validate(event)
    assert parsed.event_type == "ENTRY"
    assert parsed.confidence == 0.44
    assert parsed.metadata.source_track_id == "CAM_3:7"

