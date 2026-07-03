import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from parse_test_results import build_record, main, parse_junit_xml  # noqa: E402

BARE_SUITE = """<?xml version="1.0"?>
<testsuite name="pytest" errors="0" failures="1" skipped="0" tests="4" time="2.345">
  <testcase classname="t" name="a" time="0.1" />
</testsuite>
"""

WRAPPED_SUITE = """<?xml version="1.0"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="0" failures="0" skipped="1" tests="5" time="1.0">
    <testcase classname="t" name="a" time="0.1" />
  </testsuite>
</testsuites>
"""

ZERO_TESTS = """<?xml version="1.0"?>
<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="0" time="0.0"></testsuite>
"""


def write_xml(tmp_path, content, name="report.xml"):
    path = tmp_path / name
    path.write_text(content)
    return str(path)


def test_parses_bare_testsuite(tmp_path):
    summary = parse_junit_xml(write_xml(tmp_path, BARE_SUITE))
    assert summary["tests_total"] == 4
    assert summary["tests_failed"] == 1
    assert summary["tests_passed"] == 3
    assert summary["pass_rate"] == 0.75
    assert summary["test_duration_seconds"] == 2.345


def test_parses_testsuites_wrapper(tmp_path):
    # pytest sometimes wraps the single testsuite in a testsuites element -
    # both shapes show up in the wild depending on pytest/plugin versions.
    summary = parse_junit_xml(write_xml(tmp_path, WRAPPED_SUITE))
    assert summary["tests_total"] == 5
    assert summary["tests_skipped"] == 1
    assert summary["pass_rate"] == 0.8


def test_zero_tests_gives_none_pass_rate(tmp_path):
    summary = parse_junit_xml(write_xml(tmp_path, ZERO_TESTS))
    assert summary["tests_total"] == 0
    assert summary["pass_rate"] is None


def test_build_record_uses_local_fallback_outside_ci(monkeypatch):
    # If this ran on an actual GH Actions runner, GITHUB_SHA etc. would be
    # set for real - strip them so the "local" fallback path is what's tested.
    env_vars = (
        "GITHUB_SHA",
        "GITHUB_REF_NAME",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_ACTOR",
    )
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    record = build_record({"tests_total": 1, "pass_rate": 1.0}, start_time=100.0)
    assert record["commit_sha"] == "local"
    assert record["branch"] == "local"
    assert record["pipeline_duration_seconds"] >= 0


def test_build_record_without_start_time_has_no_duration():
    record = build_record({"pass_rate": 1.0}, start_time=None)
    assert record["pipeline_duration_seconds"] is None


def test_main_errors_cleanly_on_missing_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parse_test_results.py",
            "--junit-xml",
            str(tmp_path / "missing.xml"),
            "--output",
            str(tmp_path / "out.json"),
        ],
    )
    code = main()
    assert code == 1
    assert "not found" in capsys.readouterr().err
