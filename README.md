# AI-Augmented CI/CD Pipeline

A CI/CD pipeline for a small Flask service, with one twist: it keeps a
history of its own runs (pass rate, build duration) and uses a rolling
z-score check against that history to decide whether a deploy should go
out - not just whether the tests happened to pass this one time.

## Try it in 30 seconds

No GitHub/Docker setup needed for this part - `examples/sample_history.jsonl`
is 15 fake runs with a planted regression on the last one:

```bash
pip install -r requirements-dev.txt
python scripts/detect_anomalies.py --history examples/sample_history.jsonl
```

You should see the gate call out `pass_rate` and `pipeline_duration_seconds`
as flagged, with the actual numbers (baseline mean, stdev, z-score) behind
the call. Regenerate the fixture with `python scripts/seed_demo_history.py`
if you want different random noise (`--seed` to make it reproducible).

## One-time repo setup

Both workflows push commits (`pipeline_metrics/history.jsonl`,
`deployment_state.json`) and the CD gate opens issues on anomalies, all using
the default `GITHUB_TOKEN`. None of this works until you flip a few settings
on the actual GitHub repo (these can't be set from the workflow files
themselves):

1. **Settings → Actions → General → Workflow permissions** - select
   "Read and write permissions." Without this, the bot-commit steps in
   `ci.yml`/`cd.yml` and the GHCR push in `cd.yml` will fail with a 403.
2. **Settings → General → Features** - make sure **Issues** is enabled. The
   gate job's `gh issue create` step needs it to file anomaly reports.
3. **Branch protection on `main`** - if you have required-review rules on
   `main`, the bot's direct `git push` (for history/deployment state) will be
   rejected. Either exclude the `pipeline-bot` commits from protection, or
   accept that those two specific files won't get committed until you relax
   that rule for them.
4. **Packages** - the first push to GHCR (`ghcr.io/<owner>/<repo>`) creates
   the package automatically; no separate registry setup needed, but the
   package's visibility defaults to private and is linked to the repo.

## Architecture

```
push/PR to main
      |
      v
+-----------------+     JUnit XML      +--------------------------+
|   CI (ci.yml)   | -----------------> | parse_test_results.py    |
| lint, pytest    |                    | -> one JSON metrics      |
+-----------------+                    |    record per run        |
      |                                +--------------------------+
      | (push to main only)                       |
      v                                            v
record_run_metrics.py  <---------------------------+
      |
      v
pipeline_metrics/history.jsonl   (committed to repo, one line per run)
      |
      v
+-----------------+
|  CD (cd.yml)    |
|  gate job:      |  reads history.jsonl -> detect_anomalies.py
|  - ok           |------------------------------+
|  - anomaly      |--> files a GitHub issue,      |
|    (blocks)     |    deploy job skipped         |
+-----------------+                               v
                                        +--------------------------+
                                        |  deploy job              |
                                        |  build + push to GHCR    |
                                        |  deploy.py (self-healing)|
                                        +--------------------------+
```

## Components

**`app/`** — the deployable artifact. Minimal Flask service: `/health`,
`/version`, and `/pipeline/status`, which reads `pipeline_metrics/history.jsonl`
(baked into the image at build time) and returns the last run's numbers. It's
a snapshot as of that build, not a live feed, but it means the deployed
service can actually tell you something about the pipeline that shipped it.

**`scripts/parse_test_results.py`** - turns a JUnit XML report into a single
structured JSON record: pass rate, test duration, total pipeline wall-clock
duration, commit SHA, branch, run ID.

**`scripts/record_run_metrics.py`** - appends that record as one line to
`pipeline_metrics/history.jsonl`. CI commits this file back to the repo after
every push to `main`, so the history is versioned, diffable, and doesn't
depend on an external time-series database.

**`scripts/detect_anomalies.py`** - rolling mean/stdev baseline over the last
N runs (default 10), z-score threshold of 2.5 by default. Only checks the
direction that matters: `pass_rate` dropping, `test_duration_seconds` /
`pipeline_duration_seconds` rising. Every flag comes with the mean, stdev,
and z-score behind it, both as JSON and as a plain-English line (`summarize()`)
so you're not stuck parsing JSON in a CI log. Won't flag anything until
there's `min-history` (default 5) prior runs - not enough data to have an
opinion yet, so it says so instead of guessing.

**`scripts/seed_demo_history.py`** - generates the fake history under
`examples/`. Not part of the pipeline itself, just here so the anomaly
detector has something to show off without 15 real commits first.

**`scripts/deploy.py`** - self-healing deploy. Starts the new container,
retries the health check with backoff (default: 5 attempts, 3s apart), and if
it never comes up healthy, automatically redeploys the last known-good image
tag (tracked in `deployment_state.json`, committed back to the repo the same
way as the metrics history). A tag is never rolled back to itself, so a
first-ever bad deploy fails cleanly instead of looping.

## Workflows

**`.github/workflows/ci.yml`** - on every push/PR to `main`: install, lint
(`flake8`), test (`pytest` with JUnit XML output), compute the run's metrics
record, upload it as an artifact, and (push-to-main only) append it to
`pipeline_metrics/history.jsonl` and commit that back with `[skip ci]` to
avoid a commit loop.

**`.github/workflows/cd.yml`** - triggered by `workflow_run` once CI succeeds
on `main` (guarantees CD only ever runs after a commit has passed CI). Both
jobs check out `main` directly rather than pinning to the SHA that triggered
CI: CI's own last step pushes a metrics commit on top of that SHA before CD
starts, so by the time `workflow_run` fires, `main` is both green *and*
already includes the row for the run being gated. Pinning to the older SHA
would make the gate read stale history and make the deploy job's own push
fail as a non-fast-forward.
1. `gate` job runs `detect_anomalies.py` against the history. On an anomaly
   it creates the `pipeline-anomaly` label if it doesn't exist yet (a fresh
   repo won't have it, and `gh issue create --label` just fails otherwise),
   then files an issue with the plain-English summary as the body. `deploy`
   is skipped entirely - no bad build ships on top of a regressing trend.
2. `deploy` job builds the Docker image, pushes it to GHCR tagged with both
   the commit SHA and `latest` (the SHA is still the exact commit CI tested -
   only the branch ref used for checkout changed, not what gets built), then
   runs `deploy.py` to bring it up with the retry/rollback behavior described
   above.

## Scope note

`deploy` targets the GitHub Actions runner itself, not a real host - no
external server or cloud account needed to run this end-to-end. If you want
to point it at something real, swap `deploy.py`'s `start_container()` for
your orchestrator's deploy call (`kubectl apply`, `ecs deploy`, `ssh` +
`docker compose`, whatever); the retry/rollback logic around it doesn't
need to change.

## Running locally

```bash
pip install -r requirements-dev.txt

# lint + test (+ coverage)
flake8 app tests scripts
pytest --junitxml=test-results.xml --cov=app --cov=scripts --cov-report=term-missing --cov-report=xml

# generate a metrics record and inspect it
python scripts/parse_test_results.py --junit-xml test-results.xml --output run.json
cat run.json

# check for anomalies against the tracked history
python scripts/detect_anomalies.py --history pipeline_metrics/history.jsonl

# build and run the container
docker build -t ai-cicd-demo .
docker run -p 8000:8000 ai-cicd-demo
curl localhost:8000/health
```

## Known limitations

- **No dedupe on anomaly issues.** A regression that persists across several
  runs files several issues, not one updated thread. Would need to search
  open issues by the `pipeline-anomaly` label first and comment on a match
  instead of always creating new.
- **No race protection on the bot commits.** `ci.yml`/`cd.yml` push straight
  to `main`, no `git pull --rebase` first. Two runs finishing close together
  could race and one push gets rejected non-fast-forward. Fine for a
  single-contributor repo, not fine once more people are pushing to `main`.
- **`sys.path` hack in tests.** `test_detect_anomalies.py`, `test_deploy.py`,
  `test_parse_test_results.py`, and `test_record_run_metrics.py` each do
  `sys.path.insert(...)` to import from `scripts/` since it isn't an
  installable package. Works fine, but a shared `conftest.py` would be
  cleaner than repeating it four times.

## Why bother with all this

Regressions in CI usually get noticed late - after a few bad runs pile up,
or someone mentions the build "feels slower" in standup. Keeping the run
history as data instead of just logs means the pipeline can compare each
run against its own recent baseline and catch a regression at the commit
that caused it. Pairing that with an automatic rollback on failed health
checks covers both failure modes here - the pipeline getting worse, and a
bad build reaching deploy - without needing someone to notice first.
