# Store Intelligence System Design

## Overview

This project builds a store-intelligence pipeline for the Brigade Bangalore CCTV and POS dataset. The goal is to estimate offline conversion rate from camera-derived visitor sessions and invoice-level POS transactions.

The system has four layers:

1. A detection pipeline reads CCTV clips and emits structured behavioral events.
2. An ingest API validates, deduplicates, and stores events.
3. An analytics layer computes metrics, funnel, heatmap, anomalies, and health status.
4. A replay command can stream generated events into the API for a live demonstration.
5. A lightweight dashboard consumes the API endpoints and provides a reviewer-friendly operational view of metrics, funnel, heatmap, anomalies, and health status.

The primary detection strategy is YOLOv8n person detection with ByteTrack tracking. This is chosen because the challenge evaluates group entry, occlusion, crowded billing, tracking accuracy, and re-entry handling. OpenCV background subtraction is kept only as a diagnostic/emergency fallback concept, not as the main event generator.

## Camera and Layout Configuration

The camera-role mapping lives in `data/camera_config.json`. The current mapping is an initial camera-role mapping based on visual inspection of representative frames. It is configurable because camera filenames are not guaranteed to carry semantic roles.

The config includes each camera role, region-of-interest boxes, entry-line position, and whether a camera should be excluded from customer metrics by default. This keeps the implementation flexible: if CAM numbers differ, the operator updates the JSON instead of editing code.

The detector recursively discovers `.mp4` clips and resolves camera roles through configurable aliases, allowing compatibility with both the original challenge resources and the updated Store 1 / Store 2 resource packs.

The final reviewed mapping for this dataset is:

- `CAM_1`: main-floor skincare / PMU
- `CAM_2`: main-floor makeup / accessories / PMU
- `CAM_3`: entry/exit threshold
- `CAM_4`: backroom/storage, excluded from customer metrics by config
- `CAM_5`: billing/cash-counter area

The canonical store identifier is `ST1008`, which comes from the real POS data. `Brigade_Bangalore` is the human-readable store name. `ST1008` is used across layout, camera config, POS transactions, generated events, tests, and endpoint examples.

## Event Flow

The detection pipeline emits events in the challenge schema. YOLOv8n produces person detections, ByteTrack assigns local track IDs, and the event emitter maps track movement into semantic events such as `ENTRY`, `EXIT`, `ZONE_ENTER`, `ZONE_DWELL`, and `BILLING_QUEUE_JOIN`.

The PDF-style challenge schema remains the canonical internal schema. An optional adapter is provided for organizer sample-event resources that use different field names, ensuring compatibility without changing analytics or storage models.

Re-entry is handled using heuristic session linking and probabilistic matching; it is not guaranteed person identity. The linker treats ByteTrack IDs as camera-local and creates visitor/session IDs from recent track behavior. If a new entry-side track appears near a recently exited track within a short time window, the pipeline can emit `REENTRY`. This is intentionally modest because faces are blurred and no POS customer identity is available.

Staff handling is also heuristic. Events are not deleted. The pipeline marks `is_staff=true` when behavior strongly suggests staff activity, such as backroom camera activity, long-running billing-side presence, or cash-counter-side movement. The API excludes staff from customer metrics while preserving raw events for auditability.

Short sample clips may begin after a visitor has already crossed the entry threshold. To avoid impossible funnel shapes, the analytics layer treats observed non-staff sessions as inferred entry-stage sessions when explicit entry events are absent. Explicit `ENTRY` and `REENTRY` events are still preserved and used when available.

## API and Business Metrics

The API is built with FastAPI and SQLite. `POST /events/ingest` validates and stores batches up to 500 events, deduplicating by `event_id` and returning partial-success errors for malformed events.

The metrics layer computes:

- Unique visitors from session-level visitor IDs.
- Conversion rate by matching POS transactions to sessions present in billing during the 5-minute pre-transaction window.
- Average dwell per zone from `ZONE_DWELL` events.
- Funnel stages from entry, zone visit, billing queue, and purchase.
- Heatmap-ready zone scores normalized from 0 to 100.
- Operational anomalies for queue spikes, conversion drop, dead zones, and stale feeds.

The `/health` endpoint reports `STALE_FEED` when the last event is more than 10 minutes behind current system time. That warning is expected for this submission evidence because the CCTV timestamps are historical (`2026-04-10`), not live current-time feeds.

## Deployment and Reproducibility

The submission includes Docker Compose support so evaluators can reproduce the API and analytics environment with a single command. SQLite was selected to avoid requiring external infrastructure during evaluation while still keeping the storage layer replaceable for future production deployments.

## Assumptions

- The CCTV clips are representative samples, not a full store day.
- Camera-role mapping was derived from visual inspection and is configurable via `data/camera_config.json`.
- Billing-to-POS conversion uses the challenge-defined 5-minute pre-transaction window.
- Re-entry is heuristic/probabilistic session matching, not guaranteed person identity.
- Staff detection is heuristic and based on camera role, position, and persistence.
- Historical CCTV timestamps may produce `STALE_FEED` warnings in `/health`.

## Validation Evidence

The reviewed validation sample produced 161 schema-valid events: 6 `ENTRY`, 3 `EXIT`, 3 `REENTRY`, 70 `ZONE_ENTER`, 11 `ZONE_EXIT`, 62 `ZONE_DWELL`, and 6 `BILLING_QUEUE_JOIN` events. Replay accepted all 161 events with 0 duplicates and 0 malformed failures.

Endpoint evidence is saved under `outputs/evidence/`, including metrics, funnel, health, event-quality summary, Docker startup log, and annotated camera screenshots.

## AI-Assisted Decisions

AI helped compare the original OpenCV-only idea against YOLOv8n + ByteTrack. I accepted the recommendation to use YOLOv8n + ByteTrack because the rubric rewards edge-case handling more than eliminating dependencies.

AI also helped shape the API test strategy. I kept the idea of deterministic fixture events because API scoring should not depend on model runtime, GPU availability, or a successful model download.

I overrode one earlier AI tendency: wording that sounded too confident about Re-ID. The final design says re-entry uses heuristic session linking and probabilistic matching, not guaranteed person identity. That is more honest and easier to defend in follow-up questions.
