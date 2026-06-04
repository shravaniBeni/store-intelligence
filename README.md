# Store Intelligence Challenge

Containerized FastAPI service plus YOLOv8n + ByteTrack CCTV event pipeline for the Brigade Bangalore store dataset.

## Architecture

```text
CCTV Clips
    ↓
YOLOv8n + ByteTrack
    ↓
Events (JSONL)
    ↓
POST /events/ingest
    ↓
SQLite Storage
    ↓
Metrics / Funnel / Heatmap / Anomalies
    ↓
Dashboard
```

## Dataset Identity

- Canonical `store_id`: `ST1008`
- Store name: `Brigade_Bangalore`
- Business date in source data: `2026-04-10`

`ST1008` is used consistently across `data/store_layout.json`, `data/camera_config.json`, `data/pos_transactions.csv`, generated events, tests, and API examples.

## Local Runbook

Create an environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Normalize the provided POS export into invoice-level transactions:

```powershell
python -m pipeline.prepare_pos \
  --input <pos_csv> \
  --output data/pos_transactions.csv
```

Start the API:

```powershell
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal, process the CCTV clips and replay events:

```powershell
python -m pipeline.detect \
  --clips <clips_folder> \
  --output data/events.jsonl \
  --frame-stride 10
.venv\Scripts\python -m pipeline.replay --events data\events.jsonl --api http://127.0.0.1:8000 --batch-size 200 --delay 0
```

Query the required endpoints:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/stores/ST1008/metrics
Invoke-RestMethod http://127.0.0.1:8000/stores/ST1008/funnel
Invoke-RestMethod http://127.0.0.1:8000/health
```

## Docker Runbook

Start the service:

```bash
docker compose up --build
```

The API listens on `http://localhost:8000`. In a second terminal:

```powershell
python -m pipeline.replay --events data\events.jsonl --api http://localhost:8000 --batch-size 200 --delay 0
Invoke-RestMethod http://localhost:8000/stores/ST1008/metrics
Invoke-RestMethod http://localhost:8000/stores/ST1008/funnel
Invoke-RestMethod http://localhost:8000/health
```

Docker startup evidence is saved at `outputs/evidence/docker_startup_log.txt`.
pipeline.prepare_pos supports both the original invoice-based POS export and the updated order_id-based sample POS format provided in the challenge resources.

## Dashboard

After starting the API, open:

http://localhost:8000/dashboard

The dashboard consumes the existing API endpoints and displays:

- Visitor count
- Conversion rate
- Queue depth
- Funnel analytics
- Heatmap zone statistics
- Active anomalies

The dashboard refreshes automatically every 8 seconds and also supports manual refresh.
No additional backend endpoints are required; the dashboard is a thin visualization layer over the required challenge APIs.

## Detection Strategy

The submitted primary approach is YOLOv8n + ByteTrack. It is selected over pure background subtraction because the rubric rewards group entry handling, occlusion handling, crowded billing, re-entry reasoning, and tracking accuracy.

Camera roles are configurable in `data/camera_config.json`. The current mapping was derived from visual inspection:

- `CAM_1`: main-floor skincare / PMU
- `CAM_2`: main-floor makeup / accessories / PMU
- `CAM_3`: entry/exit threshold
- `CAM_4`: backroom/storage, excluded from customer metrics by config
- `CAM_5`: billing/cash-counter area

Re-entry is handled using heuristic session linking and probabilistic matching; it is not guaranteed person identity. Staff detection is heuristic.
The detector recursively discovers .mp4 clips and maps camera roles through aliases defined in data/camera_config.json, allowing compatibility with both the original challenge resources and the updated Store 1 / Store 2 resource packs.

## Validated Evidence

The latest reviewed canonical API event log is `data/events.jsonl`. For organizer sample-schema review, the same events are exported to `outputs/evidence/sample_schema_events.jsonl`.

Final validation results:

- `161` schema-valid events
- `ENTRY: 6`
- `EXIT: 3`
- `REENTRY: 3`
- `ZONE_ENTER: 70`
- `ZONE_EXIT: 11`
- `ZONE_DWELL: 62`
- `BILLING_QUEUE_JOIN: 6`
- ingest `accepted: 161`
- ingest `duplicates: 0`
- ingest `failed: 0`
- `/metrics unique_visitors: 56`
- `/metrics queue_depth: 4`

Evidence files:

- `outputs/evidence/sample_events.jsonl`
- `outputs/evidence/sample_schema_events.jsonl`
- `outputs/evidence/event_quality_summary.json`
- `outputs/evidence/metrics_example.json`
- `outputs/evidence/funnel_example.json`
- `outputs/evidence/health_example.json`
- `outputs/evidence/validation_summary.json`
- `outputs/evidence/annotated_screenshots/`

Annotated CCTV screenshots were generated locally for validation but are not committed because the challenge footage is restricted and should not be redistributed.

Known limitations:

- Re-entry is heuristic and not identity proof.
- Staff detection is heuristic.
- Conversion remains `0` for the reviewed sample because detected billing events do not fall within the configured 5-minute POS correlation window before a transaction.
- `STALE_FEED` is expected because the CCTV timestamps are historical.

## Quality Verification

Latest validation results:

- 20 tests passed
- 89% code coverage
- Docker validation successful
- Health endpoint verified
- Metrics/Funnel/Heatmap/Anomalies verified
