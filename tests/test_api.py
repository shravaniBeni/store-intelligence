# PROMPT: Generate API tests for the Store Intelligence challenge covering ingest idempotency, malformed-event partial success, zero traffic, all-staff exclusion, POS conversion correlation, funnel re-entry dedupe, heatmap bounds, anomalies, and health.
# CHANGES MADE: Kept the tests deterministic with handcrafted fixture events so endpoint correctness is independent of YOLO model downloads or GPU availability.

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

os.environ["STORE_DB_PATH"] = "data/test_store_intelligence.db"

from app import storage  # noqa: E402
from app.main import app  # noqa: E402


STORE_ID = "ST1008"
BASE = datetime(2026, 4, 10, 20, 10, tzinfo=timezone.utc)


def event(
    visitor_id: str,
    event_type: str,
    seconds: int,
    *,
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.81,
    queue_depth: int | None = None,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": "CAM_3" if event_type in {"ENTRY", "EXIT", "REENTRY"} else "CAM_5",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": (BASE + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": confidence,
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": zone_id,
            "session_seq": 1,
        },
    }


def client() -> TestClient:
    storage.reset_db()
    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO transactions VALUES (?, ?, ?, ?)",
            (
                "TXN_FIXTURE_1",
                STORE_ID,
                (BASE + timedelta(minutes=4)).isoformat(),
                1200.0,
            ),
        )
    return TestClient(app)


def test_ingest_is_idempotent_and_keeps_low_confidence_events():
    api = client()
    low_conf = event("VIS_LOW", "ENTRY", 1, confidence=0.22)
    response = api.post("/events/ingest", json={"events": [low_conf]})
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    duplicate = api.post("/events/ingest", json={"events": [low_conf]})
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicates"] == 1

    metrics = api.get(f"/stores/{STORE_ID}/metrics").json()
    assert metrics["unique_visitors"] == 1


def test_ingest_partial_success_for_malformed_events():
    api = client()
    valid = event("VIS_OK", "ENTRY", 1)
    invalid = {**valid, "event_id": "not-a-uuid"}
    response = api.post("/events/ingest", json={"events": [valid, invalid]})
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert len(body["failed"]) == 1


def test_metrics_exclude_staff_and_convert_billing_session():
    api = client()
    payload = [
        event("VIS_001", "ENTRY", 0),
        event("VIS_001", "ZONE_ENTER", 30, zone_id="MAKEUP_WALL"),
        event("VIS_001", "ZONE_DWELL", 65, zone_id="MAKEUP_WALL", dwell_ms=35000),
        event("VIS_001", "BILLING_QUEUE_JOIN", 180, zone_id="BILLING", queue_depth=2),
        event("VIS_STAFF", "ENTRY", 0, is_staff=True),
        event("VIS_STAFF", "ZONE_DWELL", 60, zone_id="BILLING", dwell_ms=60000, is_staff=True),
    ]
    api.post("/events/ingest", json={"events": payload})
    metrics = api.get(f"/stores/{STORE_ID}/metrics").json()
    assert metrics["unique_visitors"] == 1
    assert metrics["converted_visitors"] == 1
    assert metrics["conversion_rate"] == 1.0
    assert metrics["avg_dwell_per_zone_ms"]["MAKEUP_WALL"] == 35000


def test_funnel_reentry_does_not_double_count_visitor():
    api = client()
    payload = [
        event("VIS_RETURN", "ENTRY", 0),
        event("VIS_RETURN", "EXIT", 45),
        event("VIS_RETURN", "REENTRY", 90),
        event("VIS_RETURN", "ZONE_ENTER", 120, zone_id="SKINCARE_WALL"),
        event("VIS_RETURN", "BILLING_QUEUE_JOIN", 180, zone_id="BILLING", queue_depth=1),
    ]
    api.post("/events/ingest", json={"events": payload})
    funnel = api.get(f"/stores/{STORE_ID}/funnel").json()
    counts = {stage["stage"]: stage["count"] for stage in funnel["stages"]}
    assert counts["entry"] == 1
    assert counts["billing_queue"] == 1
    assert counts["purchase"] == 1


def test_empty_store_and_heatmap_are_well_formed():
    api = client()
    metrics = api.get("/stores/EMPTY/metrics").json()
    assert metrics["unique_visitors"] == 0
    assert metrics["conversion_rate"] == 0.0

    api.post("/events/ingest", json={"events": [event("VIS_001", "ZONE_ENTER", 20, zone_id="ACCESSORIES")]})
    heatmap = api.get(f"/stores/{STORE_ID}/heatmap").json()
    assert heatmap["data_confidence"] == "LOW"
    assert all(0 <= zone["normalized_score"] <= 100 for zone in heatmap["zones"])


def test_anomalies_and_health_are_structured():
    api = client()
    api.post(
        "/events/ingest",
        json={
            "events": [
                event("VIS_Q1", "ENTRY", 0),
                event("VIS_Q1", "BILLING_QUEUE_JOIN", 60, zone_id="BILLING", queue_depth=4),
            ]
        },
    )
    anomalies = api.get(f"/stores/{STORE_ID}/anomalies").json()
    assert any(item["type"] == "BILLING_QUEUE_SPIKE" for item in anomalies["active_anomalies"])

    health = api.get("/health").json()
    assert health["status"] == "ok"
    assert STORE_ID in health["stores"]


def test_health_reports_database_unavailable(monkeypatch):
    client()

    def fail_fetch_all_events():
        raise OSError("database path unavailable")

    monkeypatch.setattr(storage, "fetch_all_events", fail_fetch_all_events)
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    assert body["error"]["type"] == "OSError"
