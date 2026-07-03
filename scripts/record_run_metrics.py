"""Append one run's metrics record (from parse_test_results.py) to
pipeline_metrics/history.jsonl. That's the file detect_anomalies.py reads.
"""
import argparse
import json
import os


def append_record(record_path: str, history_path: str) -> dict:
    with open(record_path) as f:
        record = json.load(f)

    os.makedirs(os.path.dirname(history_path) or ".", exist_ok=True)
    with open(history_path, "a") as f:
        f.write(json.dumps(record) + "\n")

    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, help="Path to the single-run JSON record")
    parser.add_argument(
        "--history", required=True, help="Path to the JSONL history file to append to"
    )
    args = parser.parse_args()

    record = append_record(args.record, args.history)
    print(f"Appended run {record.get('run_id')} to {args.history}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
