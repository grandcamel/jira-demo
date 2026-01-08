# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

Live demo system for [JIRA Assistant Skills](https://github.com/grandcamel/jira-assistant-skills) plugin. Web-based terminal access via ttyd with queue/waitlist for single-user sessions against a JIRA sandbox.

```
queue-manager/     # Node.js server managing demo sessions
demo-container/    # Docker image with Claude + JIRA plugin
scripts/           # Python scripts for JIRA sandbox management
observability/     # LGTM stack configuration
```

## Quick Start

```bash
make dev                              # Start local (http://localhost:8080)
make invite-local                     # Generate invite URL
make run-scenario SCENARIO=issue      # Run autoplay in debug mode
make reset-sandbox                    # Reset JIRA sandbox
```

## Key Constraints

- **Git workflow**: Never push to `main`. Always create PR branch, rebase merge only. Delete branches after merge.
- **Secrets**: Never commit `secrets/`. Use env vars for JIRA credentials.
- **Seed issues**: Identified by `demo` label. User issues (no label) deleted on cleanup.
- **Slash commands**: Prefer Makefile targets over inline bash.

## Gotchas

- **OAuth token expires**: Run `make check-token` before skill tests. If expired, run `/refresh-token`.
- **JIRA keys auto-increment**: Reseeding creates new keys (DEMO-84+), not DEMO-1. Prompts must use current keys.
- **Rebuild after prompt changes**: Container caches scenarios. Run `make build` after editing `.prompts` files.
- **Prompts run independently**: No conversation context between prompts. Use explicit issue keys, not "that bug". Use `CONVERSATION=1` for multi-prompt context. Add `FAIL_FAST=1` to stop on first failure.
- **Session forking**: Use `--resume <session-id> --fork-session` to fork from a checkpoint (not `--continue --session-id`). Sessions persist in `~/.claude/projects/`.
- **YAML parses numbers**: `must_contain: [30]` becomes int. Code must handle with `str(pattern)`.
- **OTEL traces need flush**: Python scripts must call `force_flush()` before exit or traces won't be sent to Tempo.
- **Tempo query port**: Port 3200 must be exposed in docker-compose.dev.yml to query traces via API.
- **Skill test telemetry**: Enabled by default. Use `--no-debug` to disable. Logs to Loki, traces to Tempo.
- **Custom base image**: Use `make build BASE_IMAGE=your-registry/image:tag` for corporate certs (Zscaler).
- **Container telemetry network**: Standalone containers use external `demo-telemetry-network`. Created by `make dev`. See "Parallel Container Telemetry" section.
- **LGTM Grafana provisioning path**: The LGTM image uses `/otel-lgtm/grafana/conf/provisioning/dashboards/`, NOT `/etc/grafana/provisioning/`. Mount dashboard configs there.
- **Grafana direct dev access**: To access Grafana directly on port 3001 (bypassing nginx), set `GF_SERVER_ROOT_URL=http://localhost:3001/` and `GF_SERVER_SERVE_FROM_SUB_PATH=false` in docker-compose.dev.yml.
- **Loki stat panel queries**: Plain log queries with `count` reduction don't work for stat panels. Use metric queries: `sum by () (count_over_time({job="skill-test"} |= \`event\` [$__range]))`.
- **LogQL JSON field filtering**: Use backticks for string values: `| json | quality = \`high\``. Without backticks, Loki treats it as a label reference.
- **Duplicate logs inflate counts**: If stat panels show inflated counts (~60x expected), logs may be duplicated in Loki. Use `sum by (field)` to aggregate correctly.
- **Skill routing failures**: Common test failure pattern: jira-assistant hub routes to `jira-assistant-setup` instead of specific skills (`jira-search`, `jira-issue`, `jira-fields`). Check skill descriptions and routing logic.

## Architecture

```
nginx --> queue-manager --> ttyd --> demo-container
              |               |
           redis          LGTM stack
```

**Endpoints**: `/` landing, `/terminal` WebSocket, `/api/*` queue manager, `/grafana/` dashboards

## Common Operations

| Task | Command |
|------|---------|
| Start/stop local | `make dev` / `make dev-down` |
| Health check | `make health-local` |
| View logs | `make logs` |
| Create invite | `make invite-local` |
| Reset sandbox | `make reset-sandbox` |
| Run scenario | `make run-scenario SCENARIO=search` |
| Test skills | `make test-skill-dev SCENARIO=search` |
| Test with context | `make test-skill-dev SCENARIO=search CONVERSATION=1` |
| Test with fail-fast | `make test-skill-dev SCENARIO=search CONVERSATION=1 FAIL_FAST=1` |
| Fork from checkpoint | `make test-skill-dev SCENARIO=search FORK_FROM=0 PROMPT_INDEX=1` |
| Test with mock API | `make test-skill-mock-dev SCENARIO=search` |
| Parallel mock tests | `make test-all-mocks` |
| Parallel (specific) | `make test-all-mocks SCENARIOS=search,issue` |
| Refine skills | `make refine-skill SCENARIO=search` |
| Shell access | `make shell-queue` / `make shell-demo` |

## Git (Quick Reference)

```bash
git checkout -b feature/my-change
git push -u origin feature/my-change
gh pr create
gh pr merge --rebase --delete-branch
```

## Observability (Quick Reference)

**Metrics**: `demo_queue_size`, `demo_sessions_active`, `demo_session_duration_seconds`

**Logs**: Query Loki with `{job="autoplay"}`, `{job="skill-test"}`, or `{job="nginx"}`

**Traces**: Spans prefixed `cleanup.*`, `seed.*`, `skill_test.*`, `claude.*` in Tempo

**Grafana Dashboards** (dev: http://localhost:3001 - no auth required):

| Dashboard | Purpose |
|-----------|---------|
| Demo Overview | Queue status, active sessions, invite stats |
| Skill Test Results | Parallel test telemetry: prompts, responses, quality, durations |
| Session Analytics | User session metrics and patterns |
| Queue Operations | Queue manager operations and performance |
| Nginx Access Logs | Request logs and traffic analysis |
| System Overview | Infrastructure health metrics |

**Skill Test Results Dashboard Features:**
- Stat panels: Test Runs, High/Medium/Low Quality counts, Errors, Prompts
- Filter by scenario (search, issue, agile, etc.) and log level
- Quality distribution over time (high/medium/low) with correct aggregation
- Prompt durations by scenario (mean/max)
- Tables: Judge analysis, prompt completions, tool usage, test summaries, assertion failures
- Direct trace links to Tempo
- Raw log viewer with level filtering
- Dashboard links to other dashboards in header

## Parallel Container Telemetry

Standalone `docker run` containers share an external network with compose services for telemetry access.

**External network:** `demo-telemetry-network`
- Created automatically by `make dev`, `make deploy`, or `make start-local`
- Shared between compose services and standalone containers
- Containers resolve `lgtm` hostname directly

**Usage pattern:**
```bash
docker run --rm \
    --network demo-telemetry-network \
    -e OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318 \
    -e LOKI_ENDPOINT=http://lgtm:3100 \
    jira-demo-container:latest ...
```

**Key details:**
- All Makefile targets (`run-scenario`, `test-skill-*`, `shell-demo`) use this network automatically
- Multiple containers can run in parallel, all sending telemetry to the same LGTM stack
- Network persists after `make dev-down` (allows running tests without full stack)
- Manual creation: `docker network create demo-telemetry-network`

## Parallel Mock Testing

Run all scenarios with mocked JIRA API in parallel:

```bash
# Run all 11 scenarios with 4 workers (default)
make test-all-mocks

# Run specific scenarios
make test-all-mocks SCENARIOS=search,issue,agile

# Adjust parallelism
make test-all-mocks MAX_WORKERS=6 VERBOSE=1
```

**Key details:**
- Uses `scripts/parallel-mock-test.py` orchestrator
- Generates `PLAN-{scenario}-mock.md` for each failure with fix context
- All containers share `demo-telemetry-network` for telemetry
- 10-minute timeout per scenario
- Exit code 0 if all pass, 1 if any fail

**PLAN file contents:**
- Summary with quality rating (high/medium/low)
- Failure details: prompt text, tools called, tool accuracy
- Failed assertions table with pass/fail status
- Judge analysis: reasoning, refinement suggestion, expectation suggestion
- Test commands for iteration

## Skill Test Iteration Workflow

Fast iteration on multi-prompt scenarios without replaying all prompts:

```bash
# Step 1: Run full scenario to build checkpoints (stops on first failure)
make test-skill-dev SCENARIO=issue CONVERSATION=1 FAIL_FAST=1
# Creates /tmp/checkpoints/issue.json with session IDs for each prompt

# Step 2: If prompt 7 (index 6) fails, iterate on just that prompt
make test-skill-dev SCENARIO=issue FORK_FROM=5 PROMPT_INDEX=6
# Forks from checkpoint 5 (state after prompt 6 passed), runs only prompt 7
```

**Key details:**
- Prompts are 0-indexed: prompt 7 = PROMPT_INDEX=6, fork after prompt 6 = FORK_FROM=5
- Tests run all prompts by default; use `FAIL_FAST=1` to stop early
- Sessions persist in `/tmp/claude-sessions/` across container runs
- Each fork creates a new session ID (doesn't corrupt the checkpoint)

## Level 2 Reference

Detailed documentation in `docs/CLAUDE-L2.md`:

| Section | Content |
|---------|---------|
| Full Command Reference | All make targets with descriptions |
| Slash Commands | Complete list of `/` commands |
| Environment Variables | Required and optional env vars |
| Telemetry Reference | Loki labels, Prometheus metrics, Tempo spans |
| WebSocket Protocol | Client/server message formats |
| JIRA Sandbox Details | Projects, accounts, seed issues |
| Production Deployment | SSH, deploy workflow, DNS, SSL |
| Docker Compose | Ports, file layering |
| Autoplay Scenarios | Available scenarios, debug mode |
| Skill Testing | Test framework, refinement loop, fix agent |
| Claude Code Plugins | Plugin installation and development |
