"""Turn a JUnit XML report into one JSON metrics record (pass rate, durations,
commit/run metadata). record_run_metrics.py appends the output to the history
file detect_anomalies.py reads later.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


def parse_junit_xml(path: str) -> dict:
    tree = ET.parse(path)
    root = tree.getroot()

    # pytest wraps a single <testsuite> in <testsuites>; handle both shapes.
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise ValueError(f"No <testsuite> element found in {path}")

    tests = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    test_duration_seconds = float(suite.get("time", 0.0))

    passed = tests - failures - errors - skipped
    pass_rate = round(passed / tests, 4) if tests > 0 else None

    return {
        "tests_total": tests,
        "tests_passed": passed,
        "tests_failed": failures,
        "tests_errored": errors,
        "tests_skipped": skipped,
        "pass_rate": pass_rate,
        "test_duration_seconds": round(test_duration_seconds, 3),
    }


def build_record(junit_summary: dict, start_time: float | None) -> dict:
    now = time.time()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": os.environ.get("GITHUB_SHA", "local"),
        "branch": os.environ.get("GITHUB_REF_NAME", "local"),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "actor": os.environ.get("GITHUB_ACTOR", "local"),
    }
    record.update(junit_summary)
    record["pipeline_duration_seconds"] = (
        round(now - start_time, 3) if start_time is not None else None
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit-xml", required=True, help="Path to JUnit XML report")
    parser.add_argument(
        "--start-time",
        type=float,
        default=None,
        help="Unix timestamp when the pipeline job started (for total duration)",
    )
    parser.add_argument("--output", required=True, help="Path to write the JSON record")
    args = parser.parse_args()

    if not os.path.exists(args.junit_xml):
        print(f"error: JUnit XML file not found: {args.junit_xml}", file=sys.stderr)
        return 1

    summary = parse_junit_xml(args.junit_xml)
    record = build_record(summary, args.start_time)

    with open(args.output, "w") as f:
        json.dump(record, f, indent=2)
        f.write("\n")

    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
