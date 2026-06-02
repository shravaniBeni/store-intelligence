from __future__ import annotations

import csv
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.models import StoreEvent


DEFAULT_DB_PATH = Path(os.getenv("STORE_DB_PATH", "data/store_intelligence.db"))


def db_path() -> Path:
    return Path(os.getenv("STORE_DB_PATH", str(DEFAULT_DB_PATH)))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              event_id TEXT PRIMARY KEY,
              store_id TEXT NOT NULL,
              camera_id TEXT NOT NULL,
              visitor_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              timestamp TEXT NOT NULL,
              zone_id TEXT,
              dwell_ms INTEGER NOT NULL,
              is_staff INTEGER NOT NULL,
              confidence REAL NOT NULL,
              metadata TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
              transaction_id TEXT PRIMARY KEY,
              store_id TEXT NOT NULL,
              timestamp TEXT NOT NULL,
              basket_value_inr REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_store_ts ON events(store_id, timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_visitor ON events(store_id, visitor_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_txn_store_ts ON transactions(store_id, timestamp)")


def reset_db() -> None:
    with connect() as conn:
        conn.execute("DROP TABLE IF EXISTS events")
        conn.execute("DROP TABLE IF EXISTS transactions")
    init_db()


def insert_events(events: list[StoreEvent]) -> tuple[int, int]:
    accepted = 0
    duplicates = 0
    with connect() as conn:
        for event in events:
            try:
                conn.execute(
                    """
                    INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(event.event_id),
                        event.store_id,
                        event.camera_id,
                        event.visitor_id,
                        event.event_type.value,
                        event.timestamp.isoformat(),
                        event.zone_id,
                        event.dwell_ms,
                        int(event.is_staff),
                        event.confidence,
                        event.metadata.model_dump_json(),
                    ),
                )
                accepted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
    return accepted, duplicates


def load_transactions_csv(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", newline="") as handle, connect() as conn:
        for row in csv.DictReader(handle):
            conn.execute(
                """
                INSERT OR REPLACE INTO transactions
                (transaction_id, store_id, timestamp, basket_value_inr)
                VALUES (?, ?, ?, ?)
                """,
                (
                    row["transaction_id"],
                    row["store_id"],
                    row["timestamp"],
                    float(row["basket_value_inr"]),
                ),
            )
            count += 1
    return count


def fetch_events(store_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE store_id = ? ORDER BY timestamp, event_id",
            (store_id,),
        ).fetchall()
    return [row_to_event_dict(row) for row in rows]


def fetch_all_events() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY timestamp, event_id").fetchall()
    return [row_to_event_dict(row) for row in rows]


def fetch_transactions(store_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE store_id = ? ORDER BY timestamp",
            (store_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def row_to_event_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["is_staff"] = bool(item["is_staff"])
    item["metadata"] = json.loads(item["metadata"])
    item["timestamp_dt"] = datetime.fromisoformat(item["timestamp"])
    return item

