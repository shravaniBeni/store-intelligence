# Final Submission Checklist

## Documentation

- PASS - `README.md` includes local install/run commands, CCTV processing, event replay, endpoint calls, Docker command, evidence references, and `ST1008` dataset identity.
- PASS - `docs/DESIGN.md` includes final camera mapping, configurable camera config, inferred-session behavior, stale-feed explanation, assumptions, and limitations.
- PASS - `docs/CHOICES.md` explains YOLOv8n + ByteTrack selection, OpenCV diagnostic-only fallback, probabilistic Re-ID, and zero conversion for the reviewed sample.

## Store ID Consistency

- PASS - Canonical `store_id` is `ST1008`.
- PASS - `data/store_layout.json`, `data/camera_config.json`, `data/pos_transactions.csv`, `data/events.jsonl`, README examples, and tests use `ST1008`.
- PASS - No legacy challenge sample store IDs were found in README/tests.

## Evidence Files

- PASS - `outputs/evidence/sample_events.jsonl`
- PASS - `outputs/evidence/event_quality_summary.json`
- PASS - `outputs/evidence/ingest_example.json`
- PASS - `outputs/evidence/metrics_example.json`
- PASS - `outputs/evidence/funnel_example.json`
- PASS - `outputs/evidence/heatmap_example.json`
- PASS - `outputs/evidence/anomalies_example.json`
- PASS - `outputs/evidence/health_example.json`
- PASS - `outputs/evidence/validation_summary.json`
- PASS - `outputs/evidence/docker_startup_log.txt`
- PASS - `outputs/evidence/annotated_screenshots/`

## Validation Results

- PASS - `python -m pytest --cov=app --cov=pipeline tests`: 14 passed, total coverage 89%.
- PASS - Coverage target: 89% total coverage, above the >70% challenge target.
- PASS - Prompt blocks: every test file includes `# PROMPT:` and `# CHANGES MADE:`.
- PASS - `python -m compileall app pipeline tests -q`: passed.
- PASS - `docker compose up --build`: Docker startup confirmed after Docker Desktop was fixed.
- PASS - Docker API startup and DB initialization: Uvicorn startup complete.
- PASS - Docker `POST /events/ingest`: returned 200.
- PASS - Docker `GET /stores/ST1008/metrics`: returned 200.
- PASS - Docker `GET /stores/ST1008/funnel`: returned 200.
- PASS - Docker `GET /stores/ST1008/heatmap`: returned 200.
- PASS - Docker `GET /stores/ST1008/anomalies`: returned 200.
- PASS - Docker `GET /health`: returned 200.
- PASS - Structured logs include trace_id, store_id, endpoint, latency_ms, and status_code.
- PASS - Local API replay: accepted 161, duplicates 0, failed 0.
- PASS - Local metrics: unique_visitors 56, queue_depth 4.
- PASS - Local funnel: coherent stage counts.
- PASS - Local heatmap: returned normalized zone scores.
- PASS - Local anomalies: returned queue spike and conversion drop anomalies.
- PASS - Local health: status ok, expected `STALE_FEED`.
- PASS - Graceful database failure handling: `/health` now returns structured degraded status when database access fails.

## Known Limitations

- Re-entry is heuristic/probabilistic session matching, not identity proof.
- Staff detection is heuristic.
- Conversion remains 0 for the reviewed sample because detected billing events do not fall within the configured 5-minute POS correlation window before a transaction.
- `STALE_FEED` is expected because CCTV timestamps are historical.
