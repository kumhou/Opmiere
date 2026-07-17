# CI policy (local-first, zero hosted minutes)

## Problem we fixed

Opmiere is a **private** repo. Continuous ship on `main` ran
`.github/workflows/ci.yml` on **`windows-latest`** (GitHub-hosted). That
consumes Actions minutes (Windows is 2×). After the free/included quota
was exhausted, every push produced a **failed** check in ~1s with:

- `steps: []`
- `runner_id: 0` / empty `runner_name`
- no pytest output

That is **not a test failure** — the job never got a runner. Burning more
hosted minutes cannot “fix” it without buying more quota.

## Permanent policy

| Path | When | Minutes |
|------|------|---------|
| **`scripts/ci.ps1`** | Always — canonical gate | None (local) |
| **`scripts/ci.ps1 -Quick`** | Fast doctor + pytest | None (local) |
| **Optional pre-push hook** | `scripts/install-ci-hook.ps1` | None (local) |
| **GHA `workflow_dispatch`** | Manual only, **self-hosted** runner | None (self-hosted) |
| ~~push → `windows-latest`~~ | **Removed permanently** | Would burn quota |

Push and pull_request triggers on GitHub-hosted runners are **not** used.

## Local commands

```powershell
# From repo root (ffmpeg + pip install -e ".[dev,web]" assumed)
powershell -ExecutionPolicy Bypass -File .\scripts\ci.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\ci.ps1 -Quick
powershell -ExecutionPolicy Bypass -File .\scripts\ci.ps1 -SkipDogfood

# Optional push gate
powershell -ExecutionPolicy Bypass -File .\scripts\install-ci-hook.ps1
# Bypass once: git push --no-verify
```

What full CI runs (mirrors the old hosted job):

1. `python -m opmiere doctor --no-comfy --json`
2. `python -m pytest tests/ -q --tb=line` (`OPMIERE_SKIP_COMFY=1`)
3. `scripts/dogfood_pro_pipeline.py --seconds 1.5`
4. `scripts/dogfood_template_pipeline.py --seconds 1.2 --template talking_head`
5. `scripts/dogfood_agent_pipeline.py --seconds 1.2 --template talking_head`

## Optional: self-hosted runner on this PC

Free on private repos (does not use hosted minutes):

1. Repo → **Settings → Actions → Runners → New self-hosted runner → Windows**
2. Follow GitHub’s install/start instructions
3. Add labels: `self-hosted`, `Windows`, `opmiere` (the workflow requires them)
4. Keep the runner process/service running when you want GH checks
5. **Actions → ci → Run workflow** (`workflow_dispatch`)

Do **not** switch `runs-on` back to `windows-latest` / `ubuntu-latest` for
routine CI — that reintroduces the minutes failure mode.

## Agent / ship checklist

Before push to `main` on a non-trivial change:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ci.ps1 -Quick
# or full scripts/ci.ps1 for delivery-path changes
```

Commit messages that only touch docs/CI may use `[skip ci]` out of habit;
with push triggers removed it is optional.
