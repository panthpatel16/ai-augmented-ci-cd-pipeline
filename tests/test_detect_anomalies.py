import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from detect_anomalies import detect, summarize  # noqa: E402


def make_run(run_id, pass_rate=1.0, test_duration=5.0, pipeline_duration=40.0):
    return {
        "run_id": run_id,
        "commit_sha": f"sha{run_id}",
        "pass_rate": pass_rate,
        "test_duration_seconds": test_duration,
        "pipeline_duration_seconds": pipeline_duration,
    }


def test_insufficient_data_below_min_history():
    records = [make_run(i) for i in range(3)]
    report = detect(records, window=10, min_history=5, threshold=2.5)
    assert report["overall_status"] == "insufficient_data" or all(
        m["status"] == "insufficient_data" for m in report["metrics"].values()
    )


def test_stable_history_is_ok():
    records = [make_run(i) for i in range(10)]
    report = detect(records, window=10, min_history=5, threshold=2.5)
    assert report["overall_status"] == "ok"
    assert report["anomalous_metrics"] == []


def test_pass_rate_drop_is_flagged():
    records = [make_run(i, pass_rate=1.0) for i in range(9)]
    records.append(make_run(9, pass_rate=0.4))
    report = detect(records, window=10, min_history=5, threshold=2.5)
    assert report["overall_status"] == "anomaly"
    assert "pass_rate" in report["anomalous_metrics"]


def test_pass_rate_rise_is_not_flagged():
    # Going from 0.8 baseline to 1.0 is an improvement, not a regression.
    records = [make_run(i, pass_rate=0.8) for i in range(9)]
    records.append(make_run(9, pass_rate=1.0))
    report = detect(records, window=10, min_history=5, threshold=2.5)
    assert report["metrics"]["pass_rate"]["status"] == "ok"


def test_duration_spike_is_flagged():
    records = [make_run(i, pipeline_duration=40.0) for i in range(9)]
    records.append(make_run(9, pipeline_duration=400.0))
    report = detect(records, window=10, min_history=5, threshold=2.5)
    assert report["overall_status"] == "anomaly"
    assert "pipeline_duration_seconds" in report["anomalous_metrics"]


def test_duration_speedup_is_not_flagged():
    records = [make_run(i, pipeline_duration=40.0) for i in range(9)]
    records.append(make_run(9, pipeline_duration=5.0))
    report = detect(records, window=10, min_history=5, threshold=2.5)
    assert report["metrics"]["pipeline_duration_seconds"]["status"] == "ok"


def test_zero_variance_baseline_does_not_crash():
    # All prior runs identical -> stdev would be 0 without the safety floor.
    records = [make_run(i, test_duration=5.0) for i in range(9)]
    records.append(make_run(9, test_duration=5.0))
    report = detect(records, window=10, min_history=5, threshold=2.5)
    assert report["metrics"]["test_duration_seconds"]["status"] == "ok"


def test_empty_history():
    report = detect([], window=10, min_history=5, threshold=2.5)
    assert report["overall_status"] == "insufficient_data"


def test_window_limits_baseline_size():
    records = [make_run(i, pass_rate=1.0) for i in range(20)]
    records.append(make_run(20, pass_rate=1.0))
    report = detect(records, window=5, min_history=3, threshold=2.5)
    assert report["metrics"]["pass_rate"]["baseline_n"] == 5


def test_summarize_insufficient_data():
    report = detect([], window=10, min_history=5, threshold=2.5)
    text = summarize(report)
    assert "not enough" in text.lower()


def test_summarize_flags_the_anomalous_metric():
    records = [make_run(i, pass_rate=1.0) for i in range(9)]
    records.append(make_run(9, pass_rate=0.4))
    report = detect(records, window=10, min_history=5, threshold=2.5)
    text = summarize(report)
    assert "anomalous" in text.lower()
    assert "pass_rate" in text
    assert "FLAGGED" in text
    # a metric that's fine shouldn't get the flag marker
    assert "test_duration_seconds: 5.0" in text
    ok_line = [line for line in text.splitlines() if "test_duration_seconds" in line][0]
    assert "FLAGGED" not in ok_line


def test_summarize_ok_has_no_flags():
    records = [make_run(i) for i in range(10)]
    report = detect(records, window=10, min_history=5, threshold=2.5)
    text = summarize(report)
    assert "looks fine" in text
    assert "FLAGGED" not in text
