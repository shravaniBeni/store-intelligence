from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from app import analytics, storage
from app.models import IngestFailure, IngestRequest, IngestResponse, StoreEvent


logger = logging.getLogger("store_intelligence")
logging.basicConfig(level=logging.INFO, format="%(message)s")


app = FastAPI(title="Store Intelligence API", version="1.0.0")
STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
def startup() -> None:
    storage.init_db()
    storage.load_transactions_csv(Path("data/pos_transactions.csv"))


@app.middleware("http")
async def structured_logging(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        {
            "trace_id": trace_id,
            "store_id": request.path_params.get("id"),
            "endpoint": request.url.path,
            "latency_ms": latency_ms,
            "status_code": response.status_code,
        }
    )
    response.headers["x-trace-id"] = trace_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception):
    logger.exception("Unhandled API failure: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "error": "SERVICE_UNAVAILABLE",
            "message": "Store intelligence service is temporarily unavailable.",
        },
    )


@app.post("/events/ingest", response_model=IngestResponse)
async def ingest(payload: Any = Body(...)):
    raw_events = payload.get("events", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_events, list) or len(raw_events) > 500:
        return JSONResponse(
            status_code=422,
            content={"error": "INVALID_BATCH", "message": "events must be a list of up to 500 items"},
        )
    valid: list[StoreEvent] = []
    failed: list[IngestFailure] = []
    for index, item in enumerate(raw_events):
        try:
            valid.append(StoreEvent.model_validate(item))
        except ValidationError as exc:
            failed.append(IngestFailure(index=index, error=str(exc.errors()[0]["msg"])))
    accepted, duplicates = storage.insert_events(valid)
    return IngestResponse(accepted=accepted, duplicates=duplicates, failed=failed)


@app.get("/stores/{id}/metrics")
async def get_metrics(id: str):
    return analytics.metrics(id)


@app.get("/stores/{id}/funnel")
async def get_funnel(id: str):
    return analytics.funnel(id)


@app.get("/stores/{id}/heatmap")
async def get_heatmap(id: str):
    return analytics.heatmap(id)


@app.get("/stores/{id}/anomalies")
async def get_anomalies(id: str):
    return analytics.anomalies(id)


@app.get("/dashboard")
async def get_dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/health")
async def get_health():
    return analytics.health()
