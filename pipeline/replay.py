from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib import request


def replay(events_path: Path, api: str, batch_size: int, delay: float) -> None:
    batch = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        batch.append(json.loads(line))
        if len(batch) == batch_size:
            post_batch(api, batch)
            batch = []
            time.sleep(delay)
    if batch:
        post_batch(api, batch)


def post_batch(api: str, events: list[dict]) -> None:
    body = json.dumps({"events": events}).encode("utf-8")
    req = request.Request(
        f"{api.rstrip('/')}/events/ingest",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=15) as response:
        print(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default=Path("data/events.jsonl"), type=Path)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--batch-size", default=50, type=int)
    parser.add_argument("--delay", default=0.25, type=float)
    args = parser.parse_args()
    replay(args.events, args.api, args.batch_size, args.delay)


if __name__ == "__main__":
    main()

