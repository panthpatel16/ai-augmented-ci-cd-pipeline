"""Flag anomalies in pipeline_metrics/history.jsonl using a rolling z-score.

Compares the latest run to the mean/stdev of the last --window prior runs.
pass_rate only gets flagged if it drops; the duration metrics only get
flagged if they rise - going faster or passing more tests isn't a problem.
Won't flag anything until there's at least --min-history prior runs, since
a z-score over 1-2 data points doesn't mean much.

Exit 0 = clean, 1 = anomaly. That's what the CD gate checks.
"""
import argparse
import json
import os
import statistics

METRIC_DIRECTIONS = {
    # metric_name: "drop" (bad if it goes down) or "rise" (bad if it goes up)
    "pass_rate": "drop",
    "test_duration_seconds": "rise",
    "pipeline_duration_seconds": "rise",
}


def load_history(path: str) -> list:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def safe_stdev(values: list, mean: float) -> float:
    # floor stdev at ~1% of the mean so a dead-flat baseline doesn't
    # divide by zero and turn any tiny wobble into a massive z-score
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    floor = max(abs(mean) * 0.01, 1e-6)
    return max(stdev, floor)


def evaluate_metric(metric: str, direction: str, current, baseline_values, threshold) -> dict:
    if current is None or len(baseline_values) == 0:
        return {"status": "insufficient_data"}

    mean = statistics.mean(baseline_values)
    stdev = safe_stdev(baseline_values, mean)
    z = (current - mean) / stdev

    is_anomaly = z <= -threshold if direction == "drop" else z >= threshold

    return {
        "status": "anomaly" if is_anomaly else "ok",
        "current": round(current, 4),
        "baseline_mean": round(mean, 4),
        "baseline_stdev": round(stdev, 4),
        "baseline_n": len(baseline_values),
        "z_score": round(z, 3),
        "threshold": threshold,
        "direction_checked": direction,
    }


def detect(records: list, window: int, min_history: int, threshold: float) -> dict:
    if not records:
        return {"overall_status": "insufficient_data", "reason": "no history", "metrics": {}}

    latest = records[-1]
    prior = records[:-1]
    baseline = prior[-window:] if window else prior

    metrics_report = {}
    for metric, direction in METRIC_DIRECTIONS.items():
        values = [r[metric] for r in baseline if r.get(metric) is not None]
        current = latest.get(metric)

        if len(values) < min_history:
            metrics_report[metric] = {
                "status": "insufficient_data",
                "baseline_n": len(values),
                "min_history_required": min_history,
            }
            continue

        metrics_report[metric] = evaluate_metric(metric, direction, current, values, threshold)

    anomalous = [m for m, r in metrics_report.items() if r.get("status") == "anomaly"]

    return {
        "run_id": latest.get("run_id"),
        "commit_sha": latest.get("commit_sha"),
        "overall_status": "anomaly" if anomalous else "ok",
        "anomalous_metrics": anomalous,
        "metrics": metrics_report,
    }


def summarize(report: dict) -> str:
    """Plain-English version of the report, for issue bodies and CI logs -
    nobody wants to eyeball JSON to find out what broke."""
    if report["overall_status"] == "insufficient_data":
        return "Not enough run history yet to check for anomalies."

    verdict = "looks fine" if report["overall_status"] == "ok" else "looks anomalous"
    lines = [f"Run {report.get('run_id')} ({report.get('commit_sha')}) {verdict}."]

    for metric, result in report["metrics"].items():
        if result.get("status") == "insufficient_data":
            continue
        flag = "  <-- FLAGGED" if result["status"] == "anomaly" else ""
        lines.append(
            f"  {metric}: {result['current']} "
            f"(baseline {result['baseline_mean']} +/- {result['baseline_stdev']}, "
            f"z={result['z_score']}){flag}"
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", required=True, help="Path to pipeline_metrics/history.jsonl")
    parser.add_argument(
        "--window", type=int, default=10, help="Number of prior runs used as baseline"
    )
    parser.add_argument(
        "--min-history",
        type=int,
        default=5,
        help="Minimum prior runs required before flagging a metric",
    )
    parser.add_argument(
        "--z-threshold", type=float, default=2.5, help="Z-score threshold for flagging"
    )
    parser.add_argument("--output", help="Optional path to write the JSON report")
    args = parser.parse_args()

    records = load_history(args.history)
    report = detect(records, args.window, args.min_history, args.z_threshold)

    summary_text = summarize(report)
    output_text = json.dumps(report, indent=2)
    print(summary_text)
    print()
    print(output_text)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_text + "\n")
        # same basename, .txt instead of .json - the CD workflow uses this
        # as the GitHub issue body instead of dumping raw JSON on people
        summary_path = os.path.splitext(args.output)[0] + ".txt"
        with open(summary_path, "w") as f:
            f.write(summary_text + "\n")

    return 1 if report["overall_status"] == "anomaly" else 0


if __name__ == "__main__":
    raise SystemExit(main())
