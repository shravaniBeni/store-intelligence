# Engineering Choices

## 1. Detection Model: YOLOv8n + ByteTrack

I considered two detection approaches for the CCTV pipeline.

The first option was OpenCV background subtraction with centroid tracking. This is attractive because it has few dependencies, runs fast, and is easy to explain. I initially considered it as the default because the reviewer run window is short and a submission that fails to start is rejected before scoring. The weakness is that this approach collapses exactly where the rubric is strongest: group entry, partial occlusion, crowded billing, and tracking continuity. Two people entering together can become one contour. A queue at billing can merge into a blob. Lighting changes and shadows can create false motion. It is useful as a diagnostic or emergency fallback, but I do not want it to be the submitted primary intelligence pipeline.

The second option was YOLOv8n for person detection with ByteTrack for tracking. This adds dependencies and may require downloading `yolov8n.pt`, but it is better aligned with the challenge. YOLO produces individual person boxes instead of raw motion blobs, and ByteTrack is designed to preserve tracks through low-confidence detections rather than immediately dropping them. That matters for occlusion, crowded billing, and group entry. I chose YOLOv8n rather than a larger YOLO model because this dataset is short, 1080p, and must run acceptably on an evaluator machine. The small model gives a better balance of credibility, runtime, and reproducibility.

AI initially pushed me toward the low-dependency OpenCV baseline for reliability. I revised that choice after re-reading the evaluation framework: the challenge explicitly rewards group handling, occlusion handling, crowded tracking, re-entry reasoning, and defensible engineering judgment. The final design uses YOLOv8n + ByteTrack as the primary path and keeps OpenCV background subtraction only as a diagnostic/emergency fallback mode, not a second full event-generation pipeline.

Re-entry is handled using heuristic session linking and probabilistic matching; it is not guaranteed person identity. ByteTrack IDs are camera-local tracks. The visitor/session linker compares a new track near the entry region with recent exits using time window and spatial proximity, and the design can be extended with body-crop color histograms. This is deliberately documented as probabilistic because the footage is face-blurred and POS data has no customer identity.

OpenCV background subtraction remains diagnostic/emergency-only. It is not maintained as a second submitted event-generation pipeline because doing so would split quality work across two weaker paths. The scoring rubric is better served by making the YOLOv8n + ByteTrack path understandable and auditable.

## 2. Event Schema Design

The event schema follows the challenge contract directly: every event has a globally unique `event_id`, store and camera identity, a `visitor_id`, event type, UTC timestamp, optional zone, dwell duration, staff flag, confidence, and metadata. I store raw events even when they are low confidence or staff-related. Filtering happens in the API metrics layer, not in ingestion, because the reviewer may want to inspect what the detector produced.

The `visitor_id` represents a visit-session token, not a verified human identity. This distinction matters for follow-up questions. In a real deployment, stronger cross-camera Re-ID would require calibrated cameras, richer appearance embeddings, and a privacy review. For this challenge, the goal is to make a reasonable session-level estimate that supports conversion-rate analytics without pretending to identify people.

The metadata object carries queue depth, SKU/zone label, session sequence, source track ID, and explanatory reasons for staff/re-entry heuristics. I chose this because it keeps the core schema stable while giving reviewers enough evidence to understand how a particular event was produced.

## 3. API Architecture Choice

I chose FastAPI with SQLite for the submitted implementation. FastAPI matches the challenge FAQ and makes request validation explicit through Pydantic models. SQLite is enough for this dataset and makes `docker compose up` reliable without requiring a separate database service. The storage layer is isolated so PostgreSQL could replace SQLite for a multi-store production rollout.

The ingest endpoint is idempotent by `event_id` and accepts partial success because a real detection pipeline should not lose a whole batch because one event is malformed. Metrics, funnel, heatmap, anomalies, and health are computed from stored events and POS transactions. Tests use deterministic fixture events so API correctness does not depend on model downloads or GPU availability.

The camera-role mapping is intentionally configurable through `data/camera_config.json`. The current roles are an initial camera-role mapping based on visual inspection, not a permanent assumption baked into code. If the evaluator or operator determines that camera roles differ in the actual footage, the config can be edited without changing the pipeline logic.

For the reviewed sample, conversion rate is `0`. This is not hardcoded. The detected billing queue events occur around `20:09-20:10Z`, while the relevant later POS transaction in the normalized POS file is at `20:25:04Z`. Because the challenge defines conversion as a visitor being in the billing zone during the 5-minute window before a POS transaction, the reviewed event sample does not produce a converted visitor.
