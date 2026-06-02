from __future__ import annotations

import argparse
import csv
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path


def normalize_pos(input_path: Path, output_path: Path) -> int:
    orders: OrderedDict[str, dict] = OrderedDict()
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            invoice = row["invoice_number"]
            if invoice not in orders:
                timestamp = datetime.strptime(
                    f"{row['order_date']} {row['order_time']}", "%d-%m-%Y %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                orders[invoice] = {
                    "store_id": row["store_id"],
                    "transaction_id": invoice,
                    "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                    "basket_value_inr": 0.0,
                }
            orders[invoice]["basket_value_inr"] += float(row["total_amount"] or 0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["store_id", "transaction_id", "timestamp", "basket_value_inr"],
        )
        writer.writeheader()
        for order in orders.values():
            order["basket_value_inr"] = f"{order['basket_value_inr']:.2f}"
            writer.writerow(order)
    return len(orders)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", default=Path("data/pos_transactions.csv"), type=Path)
    args = parser.parse_args()
    count = normalize_pos(args.input, args.output)
    print(f"wrote {count} transactions to {args.output}")


if __name__ == "__main__":
    main()

