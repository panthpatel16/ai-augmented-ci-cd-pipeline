"""Generate a fake pipeline_metrics history so detect_anomalies.py has
something to chew on without waiting for 15 real CI runs.

Writes N-1 healthy-looking rows plus one deliberately regressed last row
(pass rate craters, pipeline drags), so running the detector against the
output actually shows it catching something instead of just printing
"insufficient_data".
"""
import argparse
import json
import os
import random
from datetime import datetime, timedelta, timezone


def make_row(index, base_time, pass_rate, test_duration, pipeline_duration):
    timestamp = base_time + timedelta(minutes=5 * index)
    total_tests = 20
    passed = round(total_tests * pass_rate)
    return {
        "timestamp": timestamp.isoformat(),
        "commit_sha": f"demo{index:04d}",
        "branch": "main",
        "run_id": str(1000 + index),
        "run_attempt": "1",
        "actor": "demo",
        "tests_total": total_tests,
        "tests_passed": passed,
        "tests_failed": total_tests - passed,
        "tests_errored": 0,
        "tests_skipped": 0,
        "pass_rate": round(pass_rate, 4),
        "test_duration_seconds": round(test_duration, 3),
        "pipeline_duration_seconds": round(pipeline_duration, 3),
    }


def build_rows(count, seed):
    random.seed(seed)
    base_time = datetime.now(timezone.utc) - timedelta(hours=count)

    rows = [
        make_row(
            i,
            base_time,
            pass_rate=random.uniform(0.95, 1.0),
            test_duration=random.uniform(4.5, 6.0),
            pipeline_duration=random.uniform(35, 45),
        )
        for i in range(count - 1)
    ]

    # last run: real regression, not noise - this is the one the gate should catch
    rows.append(
        make_row(count - 1, base_time, pass_rate=0.4, test_duration=5.2, pipeline_duration=140.0)
    )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="examples/sample_history.jsonl")
    parser.add_argument("--rows", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = build_rows(args.rows, args.seed)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print(f"wrote {len(rows)} rows to {args.output} (last one is the planted regression)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
