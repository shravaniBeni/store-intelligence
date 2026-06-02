from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from app import storage


ZONE_IDS = [
    "SKINCARE_WALL",
    "MAKEUP_WALL",
    "ACCESSORIES",
    "PMU",
    "BILLING",
]


def customer_events(store_id: str) -> list[dict]:
    return [event for event in storage.fetch_events(store_id) if not event["is_staff"]]


def visitor_sets(events: list[dict]) -> dict[str, set[str]]:
    stages = {
        "entry": set(),
        "zone_visit": set(),
        "billing_queue": set(),
        "purchase": set(),
    }
    observed_visitors = {event["visitor_id"] for event in events}
    for event in events:
        visitor_id = event["visitor_id"]
        if event["event_type"] in {"ENTRY", "REENTRY"}:
            stages["entry"].add(visitor_id)
        if event["event_type"] in {"ZONE_ENTER", "ZONE_DWELL"} and event["zone_id"] != "BILLING":
            stages["zone_visit"].add(visitor_id)
        if event["event_type"] == "BILLING_QUEUE_JOIN" or event["zone_id"] == "BILLING":
            stages["billing_queue"].add(visitor_id)
    # Short sample clips may start after a visitor has already crossed the entry threshold.
    # Treat any observed customer session as an inferred entry-stage session so funnel
    # counts remain monotonic, while preserving explicit ENTRY/REENTRY events when present.
    stages["entry"].update(observed_visitors)
    return stages


def purchased_visitors(store_id: str, events: list[dict]) -> set[str]:
    txns = storage.fetch_transactions(store_id)
    billing_events = [
        event
        for event in events
        if event["event_type"] in {"BILLING_QUEUE_JOIN", "ZONE_ENTER", "ZONE_DWELL"}
        and event["zone_id"] == "BILLING"
    ]
    purchased: set[str] = set()
    for txn in txns:
        txn_time = datetime.fromisoformat(txn["timestamp"])
        window_start = txn_time - timedelta(minutes=5)
        candidates = [
            event
            for event in billing_events
            if window_start <= event["timestamp_dt"] <= txn_time
        ]
        if candidates:
            purchased.add(max(candidates, key=lambda event: event["timestamp_dt"])["visitor_id"])
    return purchased


def metrics(store_id: str) -> dict[str, Any]:
    events = customer_events(store_id)
    stages = visitor_sets(events)
    unique_visitors = len(stages["entry"] or {event["visitor_id"] for event in events})
    purchased = purchased_visitors(store_id, events)
    dwell_by_zone: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if event["event_type"] == "ZONE_DWELL" and event["zone_id"]:
            dwell_by_zone[event["zone_id"]].append(event["dwell_ms"])
    queue_events = [event for event in events if event["event_type"] == "BILLING_QUEUE_JOIN"]
    abandons = [event for event in events if event["event_type"] == "BILLING_QUEUE_ABANDON"]
    latest_queue_depth = 0
    if queue_events:
        latest_queue_depth = queue_events[-1]["metadata"].get("queue_depth") or 0
    return {
        "store_id": store_id,
        "unique_visitors": unique_visitors,
        "converted_visitors": len(purchased),
        "conversion_rate": round(len(purchased) / unique_visitors, 4) if unique_visitors else 0.0,
        "avg_dwell_per_zone_ms": {
            zone: round(mean(values), 2) for zone, values in sorted(dwell_by_zone.items())
        },
        "queue_depth": latest_queue_depth,
        "abandonment_rate": round(len(abandons) / len(queue_events), 4) if queue_events else 0.0,
    }


def funnel(store_id: str) -> dict[str, Any]:
    events = customer_events(store_id)
    stages = visitor_sets(events)
    stages["purchase"] = purchased_visitors(store_id, events)
    ordered = ["entry", "zone_visit", "billing_queue", "purchase"]
    result = []
    previous_count: int | None = None
    for name in ordered:
        count = len(stages[name])
        dropoff = 0.0 if previous_count in (None, 0) else round((previous_count - count) / previous_count, 4)
        result.append({"stage": name, "count": count, "dropoff_from_previous": dropoff})
        previous_count = count
    return {"store_id": store_id, "unit": "session", "stages": result}


def heatmap(store_id: str) -> dict[str, Any]:
    events = customer_events(store_id)
    sessions = len({event["visitor_id"] for event in events})
    grouped: dict[str, dict[str, Any]] = {
        zone: {"visits": 0, "dwell_values": []} for zone in ZONE_IDS
    }
    for event in events:
        zone = event["zone_id"]
        if zone not in grouped:
            continue
        if event["event_type"] == "ZONE_ENTER":
            grouped[zone]["visits"] += 1
        if event["event_type"] == "ZONE_DWELL":
            grouped[zone]["dwell_values"].append(event["dwell_ms"])
    max_visits = max([value["visits"] for value in grouped.values()] + [1])
    zones = []
    for zone, value in grouped.items():
        avg_dwell = mean(value["dwell_values"]) if value["dwell_values"] else 0
        normalized = round((value["visits"] / max_visits) * 100, 2)
        zones.append(
            {
                "zone_id": zone,
                "visit_frequency": value["visits"],
                "avg_dwell_ms": round(avg_dwell, 2),
                "normalized_score": normalized,
            }
        )
    return {
        "store_id": store_id,
        "data_confidence": "LOW" if sessions < 20 else "HIGH",
        "zones": zones,
    }


def anomalies(store_id: str) -> dict[str, Any]:
    metric = metrics(store_id)
    events = customer_events(store_id)
    latest = max((event["timestamp_dt"] for event in events), default=None)
    active = []
    if metric["queue_depth"] >= 4:
        active.append(
            {
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "CRITICAL",
                "suggested_action": "Open another billing station or assign floor staff to billing.",
            }
        )
    elif metric["queue_depth"] >= 2:
        active.append(
            {
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "WARN",
                "suggested_action": "Monitor billing counter and prepare backup cashier.",
            }
        )
    if metric["unique_visitors"] >= 3 and metric["conversion_rate"] < 0.2:
        active.append(
            {
                "type": "CONVERSION_DROP",
                "severity": "WARN",
                "suggested_action": "Check staff coverage and product assistance in high-dwell zones.",
            }
        )
    if latest:
        cutoff = latest - timedelta(minutes=30)
        visited_zones = {
            event["zone_id"]
            for event in events
            if event["zone_id"] and event["timestamp_dt"] >= cutoff
        }
        for zone in ZONE_IDS:
            if zone not in visited_zones and zone != "BILLING":
                active.append(
                    {
                        "type": "DEAD_ZONE",
                        "zone_id": zone,
                        "severity": "INFO",
                        "suggested_action": f"Review merchandising or staff guidance near {zone}.",
                    }
                )
                break
    return {"store_id": store_id, "active_anomalies": active}


def health() -> dict[str, Any]:
    try:
        events = storage.fetch_all_events()
    except Exception as exc:
        return {
            "status": "degraded",
            "database": "unavailable",
            "stores": {},
            "error": {
                "type": exc.__class__.__name__,
                "message": "Database unavailable during health check.",
            },
        }
    latest_by_store: dict[str, datetime] = {}
    for event in events:
        latest_by_store[event["store_id"]] = max(
            latest_by_store.get(event["store_id"], event["timestamp_dt"]),
            event["timestamp_dt"],
        )
    now = datetime.now(timezone.utc)
    stores = {}
    for store_id, latest in latest_by_store.items():
        lag = now - latest
        stores[store_id] = {
            "last_event_timestamp": latest.isoformat(),
            "lag_seconds": int(lag.total_seconds()),
            "warning": "STALE_FEED" if lag > timedelta(minutes=10) else None,
        }
    return {"status": "ok", "database": "ok", "stores": stores}
