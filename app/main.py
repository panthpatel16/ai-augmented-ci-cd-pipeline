"""The thing that actually gets deployed. Kept small on purpose - the
interesting part of this project is the pipeline around it, not the app."""
import json
import os

from flask import Flask, jsonify

app = Flask(__name__)

# baked into the image at build time (see Dockerfile) - a snapshot as of
# the last build, not a live feed. good enough for a status page.
HISTORY_PATH = os.environ.get("PIPELINE_HISTORY_PATH", "pipeline_metrics/history.jsonl")


@app.get("/health")
def health():
    return jsonify(status="ok"), 200


@app.get("/version")
def version():
    return jsonify(version="0.1.0"), 200


@app.get("/pipeline/status")
def pipeline_status():
    if not os.path.exists(HISTORY_PATH):
        return jsonify(available=False, reason="no history baked into this image"), 200

    with open(HISTORY_PATH) as f:
        runs = [json.loads(line) for line in f if line.strip()]

    if not runs:
        return jsonify(available=False, reason="history file is empty"), 200

    latest = runs[-1]
    return jsonify(
        available=True,
        runs_recorded=len(runs),
        latest_run={
            "commit_sha": latest.get("commit_sha"),
            "pass_rate": latest.get("pass_rate"),
            "test_duration_seconds": latest.get("test_duration_seconds"),
            "pipeline_duration_seconds": latest.get("pipeline_duration_seconds"),
        },
    ), 200


def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
