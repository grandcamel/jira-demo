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

- **Git workflow**: Local `main` is read-only (update via `git pull` only). Use local `dev` branch for new commits. Create PR branches from `dev` when ready.
- **Secrets**: Never commit `secrets/`. Only `example.env` is tracked. Use env vars for credentials.
- **Seed issues**: Identified by `demo` label. User issues (no label) deleted on cleanup.
- **Slash commands**: Prefer Makefile targets over inline bash.

## Gotchas

- **Claude auth via OAuth token**: Uses `CLAUDE_CODE_OAUTH_TOKEN` env var (not credential file mounts). On macOS, Makefile auto-retrieves from Keychain if not set. Store with: `security add-generic-password -a "$USER" -s "CLAUDE_CODE_OAUTH_TOKEN" -w "<token>"`. Get token via `claude setup-token`.
- **OAuth token needs .claude.json flags**: OAuth token auth requires `.claude.json` with `hasCompletedOnboarding` and `bypassPermissionsModeAccepted` set to true. The demo-container entrypoint creates this automatically when `CLAUDE_CODE_OAUTH_TOKEN` is set.
- **OAuth token expires**: If skill tests fail with auth errors, run `/refresh-token` to get a new token.
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
- **Dashboard reload requires container restart**: After editing dashboard JSON in `observability/dashboards/`, run `docker restart jira-demo-lgtm` to reload. Grafana's provisioning reload API is not available in the LGTM image.
- **Loki stat panel queries**: Plain log queries with `count` reduction don't work for stat panels. Use metric queries: `sum by () (count_over_time({job="skill-test"} |= \`event\` [$__range]))`.
- **LogQL JSON field filtering**: Use backticks for string values: `| json | quality = \`high\``. Without backticks, Loki treats it as a label reference.
- **Stat panel query type**: Grafana executes Loki metric queries as range queries by default, evaluating at multiple timestamps with overlapping windows. This causes stat panels to show ~60-100x inflated counts. Fix: add `"queryType": "instant"` to stat panel targets in dashboard JSON. Validate with direct Loki query: `curl 'http://localhost:3100/loki/api/v1/query' --data-urlencode 'query=sum(count_over_time({job="skill-test"} |= \`test_complete\` [1h]))'`.
- **Loki high cardinality**: Queries without aggregation may hit "maximum number of series (500) reached" error due to label combinations (scenario × level × prompt_index × quality). Always use `sum()` or filter by specific labels.
- **Skill routing failures**: Common test failure pattern: jira-assistant hub routes to `jira-assistant-setup` instead of specific skills (`jira-search`, `jira-issue`, `jira-fields`). Check skill descriptions and routing logic.
- **Plugin is documentation-only**: The JIRA Assistant Skills plugin contains only SKILL.md files (documentation). All CLI implementation is in the `jira-assistant-skills` package (source: `jira-assistant-skills-lib/` submodule).
- **Package renamed**: The package is now `jira-assistant-skills` (not `jira-assistant-skills-lib`). Install with `pip install jira-assistant-skills`. The Python module name is still `jira_assistant_skills_lib`.
- **Mock mode requires get_jira_client() check**: The `is_mock_mode()` check must be in the `get_jira_client()` convenience function (config_manager.py), not just ConfigManager methods. Skills call the convenience function via `from jira_assistant_skills_lib import get_jira_client`.
- **Telemetry reveals tool call cascades**: Loki `prompt_complete` events include `tools_called` array (e.g., `["Skill", "Bash", "Skill", "Bash"]`). Use this to diagnose unexpected tool usage patterns like credential check cascades.
- **Compare interactive vs mock tests**: When mock tests fail but interactive tests pass with the same prompt, check if the container has the latest library code. Stale container = mock client not activating = credential validation fails = Bash diagnostic cascade.
- **Mock client API parity**: Mock client methods must match real `JiraClient` signatures exactly. Common miss: `search_issues()` needs `next_page_token` parameter. Error pattern: `TypeError: MockJiraClientBase.search_issues() got an unexpected keyword argument 'next_page_token'`. Fix in `mock/base.py`, not config_manager.
- **Test CLI directly first**: Before running full `make test-skill-mock-dev`, test `jira-as` CLI commands directly to get clearer errors. See "Mock Mode Debugging" section below.
- **Mock activation vs mock errors**: Different failure patterns: (1) Mock not activating = credential validation errors + Bash cascade. (2) Mock activated but incomplete = `TypeError` on mock methods. Verify activation first with quick Python test.
- **jira-as CLI from wheel**: The `jira-as` CLI is in the `jira-assistant-skills` package (source: `jira-assistant-skills-lib/`). Install from wheel via `pip install /opt/jira-dist/*.whl`. Makefile targets mount the `dist/` directory for this.
- **Rebuild wheel after package changes**: Changes to `jira-assistant-skills` package require rebuilding the wheel (`hatch build` in `jira-assistant-skills-lib/`) before container will see them.
- **Skill cascade on failure**: When Claude calls a Skill and the subsequent Bash command fails (e.g., `jira-as` not found), it cascades: Skill → Bash (fails) → setup skill → more Bash exploration. Root cause is usually missing CLI or misconfigured environment, not skill logic. Note: `Skill → Bash` is the CORRECT pattern (see below); only failure cascades are problematic.
- **skill-test.py baked into container**: The `skill-test.py` is copied into the container image at build time. Changes to `demo-container/skill-test.py` require either `make build` OR mounting the local file. Makefile dev targets now mount it automatically: `-v $(PWD)/demo-container/skill-test.py:/workspace/skill-test.py:ro`.
- **Judge needs skill execution context**: The LLM judge evaluates tool usage. Without context about how Claude Code skills work (`Skill → Bash` pattern), it will incorrectly penalize Bash usage as "extra tools". The judge prompt in `skill-test.py` includes this context - don't remove it.
- **Conversation mode context reuse**: In `CONVERSATION=1` mode, Claude may answer from context instead of re-calling CLI when data is already available. Example: After listing issues, "What's the status of DEMO-84?" may be answered from context without Bash. This causes tool expectation failures even when responses are correct. Design prompts to require fresh data or accept context reuse as valid.
- **Scenario tool expectations pattern**: For conversation mode scenarios, first prompt should `must_call: [Skill]`, subsequent prompts should `must_call: [Bash]`. The scenarios directory is mounted in dev targets for iteration without rebuild.
- **Semantic disambiguation in prompts**: Use "jira bug" instead of just "bug" when referencing created issues. Without "jira", Claude may answer from context instead of executing CLI operations. This improved test pass rates from 50-70% to 80-90%.
- **Mock client state now persists**: File-based persistence (`/tmp/mock_state.json`) enables created issues to persist across CLI calls within the same container run. Implemented via `sitecustomize.py` import hook in `/workspace/patches/`. State resets per scenario (new container run = fresh state).
- **Mock client parameter warnings**: The mock client may log warnings for unsupported parameters (e.g., `notify_users`). Relax `must_not_contain: [error]` expectations to `must_not_contain: [failed]` for prompts that may trigger these warnings.
- **Test result variability**: Expect 10-20% variation in pass rates between identical test runs. Claude's non-deterministic responses and conversation context handling cause variability. Run tests multiple times to assess true pass rate.
- **Nginx locations.include naming**: The `locations.include` file contains `location` directives that must be inside a `server` block. It's named `.include` (not `.conf`) to prevent nginx from auto-including it via the `*.conf` pattern at the http context level.
- **Local vs production deploy**: `make deploy` requires SSL certificates at `/etc/letsencrypt/` that only exist on the production server. For local development, always use `make dev` which uses `docker-compose.dev.yml` with HTTP-only nginx config on port 8080.
- **Docker compose timeout recovery**: If `docker-compose down` times out (common with nginx), force remove the stuck container with `docker rm -f jira-demo-nginx`, then restart with `docker-compose up -d`.
- **Container mount path changes**: After renaming mounted files (e.g., `locations.conf` → `locations.include`), you must recreate the container (`docker rm -f` + `docker-compose up -d`), not just restart it. Docker caches mount paths.
- **Production env vars location**: On production (`/opt/jira-demo`), env vars must be in `.env` (project root), not `secrets/.env`. Docker-compose only reads `.env` from the project root. The `secrets/.env` is only loaded when using Makefile targets (via `include ./secrets/.env`).
- **Production SSH access**: Production is at `ssh root@assistant-skills.dev` with code in `/opt/jira-demo`. Use `make` commands via SSH: `ssh root@assistant-skills.dev "cd /opt/jira-demo && make invite"`.
- **Skill test working directory**: Skill tests must run from `/tmp` (neutral directory), not `/workspace`. When Claude sees plugin structure in working directory, it routes to setup prompts instead of executing skills. The Makefile adds `cd /tmp &&` before running tests.
- **Consolidated wheel path**: Use wheels from `jira-assistant-skills-lib/dist/` (consolidated package with CLI), not `dist/` (stale wheels that require `jira-assistant-skills-lib` from PyPI). The stale wheels cause mock mode failures because PyPI version lacks latest fixes.

## How Claude Code Skills Work

**Fundamental concept**: Claude Code skills are context-loading mechanisms, NOT direct executors.

**The correct pattern:**
1. **Skill tool** → Loads SKILL.md content into Claude's context (instructions, examples, available scripts)
2. **Bash tool** → Claude executes the CLI commands described in the skill (e.g., `jira-as search query "..."`)

**Key behaviors:**
- Skill tool is activated by YAML frontmatter matching in SKILL.md
- Once loaded, the skill context persists for the entire conversation
- Subsequent operations should use Bash directly WITHOUT re-invoking the Skill tool
- ALL Claude Code skills work this way: context-loading + Bash execution

**Expected tool sequences:**
| Scenario | Expected Tools | Notes |
|----------|---------------|-------|
| First JIRA query in conversation | `['Skill', 'Bash']` | Skill loads context, Bash runs `jira-as` CLI |
| Subsequent JIRA queries | `['Bash']` | Context already loaded, just run CLI |
| Knowledge question (no execution) | `['Skill']` | Only needs context, no CLI execution |

**Test expectation implications:**
- Tests expecting CLI execution should expect `['Skill', 'Bash']`, not just `['Skill']`
- "Tool accuracy: partial" when `Skill → Bash` is used is a FALSE NEGATIVE - this is correct behavior
- Judge refinement suggestions saying "skill should be self-contained without Bash" are INCORRECT

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
| Parallel refine | `make refine-all-mocks` |
| Parallel refine (specific) | `make refine-all-mocks SCENARIOS=search,issue MAX_ATTEMPTS=5` |
| Shell access | `make shell-queue` / `make shell-demo` |
| Run prompt non-interactively | `make shell-demo PROMPT="..." MODEL=opus` |
| Verify mock activation | See "Mock Mode Debugging" section |
| Test script directly | See "Mock Mode Debugging" section |

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

**Validate dashboard against raw telemetry:**
```bash
# Count test_complete events (should match "Test Runs" stat panel)
curl -s 'http://localhost:3100/loki/api/v1/query' \
  --data-urlencode 'query=sum(count_over_time({job="skill-test"} |= `test_complete` [1h]))' | jq '.data.result[0].value[1]'

# Count by quality (should match High/Medium/Low panels)
curl -s 'http://localhost:3100/loki/api/v1/query' \
  --data-urlencode 'query=sum(count_over_time({job="skill-test"} |= `judge_complete` | json | quality = `low` [1h]))' | jq '.data.result[0].value[1]'

# List available label values
curl -s 'http://localhost:3100/loki/api/v1/label/scenario/values' | jq '.data'
```

**Skill Test Telemetry Events:**

| Event | Key Fields | Use Case |
|-------|------------|----------|
| `prompt_start` | `prompt_text` (1000 chars) | Track when prompts begin |
| `prompt_complete` | `prompt`, `response` (5000 chars each), `tools_called`, `duration_seconds` | Full prompt/response text for debugging |
| `failure_detail` | All context: `prompt`, `response`, `tool_assertions`, `text_assertions`, `reasoning`, `refinement_suggestion` | Single event with everything needed to debug failures |
| `judge_complete` | `quality`, `tool_accuracy`, `reasoning`, `refinement_suggestion`, `expectation_suggestion` | Judge analysis with full suggestions |
| `assertion_failure` | `failed_tool_assertions`, `failed_text_assertions` | Which assertions failed |
| `test_complete` | `passed_count`, `failed_count`, `pass_rate`, `quality_high/medium/low` | Test run summary |

**Query prompt/response text from Loki:**
```bash
# Get all failure details with full context (best for debugging)
curl -s 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={job="skill-test"} |= `failure_detail` | json' \
  --data-urlencode 'start='$(date -v-1H +%s) --data-urlencode 'end='$(date +%s) \
  | jq -r '.data.result[].values[][1]' | jq '{prompt, response, quality, reasoning}'

# Get prompt/response for specific scenario and prompt index
curl -s 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={job="skill-test", scenario="issue-mock", prompt_index="4"} |= `prompt_complete` | json' \
  --data-urlencode 'start='$(date -v-1H +%s) --data-urlencode 'end='$(date +%s) \
  | jq -r '.data.result[].values[][1]' | jq '{prompt, response, tools_called}'

# List all failed prompts with their assertions
curl -s 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={job="skill-test", status="fail"} |= `failure_detail` | json' \
  --data-urlencode 'start='$(date -v-12H +%s) --data-urlencode 'end='$(date +%s) \
  | jq -r '.data.result[].values[][1]' | jq '{scenario: .scenario, prompt_index, text_assertions}'
```

**Grafana Dashboard Development Tips:**
- Use `| json` pipeline to parse structured log fields
- Filter by labels: `{job="skill-test", scenario=~"issue.*", quality="low"}`
- For tables showing prompt/response: use `| json | line_format "{{.prompt}}"` with "Logs" visualization
- Stat panels need `queryType: "instant"` in JSON to avoid count inflation
- Use `failure_detail` event for comprehensive failure tables (has all context in one event)
- Stream labels available: `job`, `scenario`, `prompt_index`, `quality`, `status`, `level`

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
- All containers share `demo-telemetry-network` for telemetry
- 20-minute timeout per scenario
- Exit code 0 if all pass, 1 if any fail
- Use `--fix-context` flag to output JSON for debugging failures

## Parallel Skill Refinement

Run refinement loops for all scenarios in parallel. Each scenario gets independent retry attempts with checkpoint-based iteration and fix agent session continuity:

```bash
# Run all 11 scenarios with 5 retries each (default)
make refine-all-mocks

# Run specific scenarios
make refine-all-mocks SCENARIOS=search,issue,agile

# Custom parallelism and retries
make refine-all-mocks MAX_WORKERS=6 MAX_ATTEMPTS=3 VERBOSE=1
```

**Key details:**
- Uses `scripts/parallel-refine-loop.py` orchestrator
- Each scenario runs independently in parallel (default: 4 workers)
- 5 retry attempts per scenario (configurable via `MAX_ATTEMPTS`)
- Checkpoint-based iteration: skips passed prompts on retry
- Fix agent maintains session continuity across attempts
- Generates `REFINE-SUMMARY.md` report with results
- Exit code 0 if all scenarios pass, 1 if any fail

**Flow per scenario:**
```
Attempt 1: Run all prompts → Fail at prompt N → Checkpoint at N-1 → Fix agent
Attempt 2: Fork from N-1 → Run prompt N → Still fails → Fix agent (same session)
Attempt 3: Fork from N-1 → Pass → Success!
```

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

## Automated Skill Refinement

The `refine-skill` target runs an automated fix loop with checkpoint-based iteration:

```bash
make refine-skill SCENARIO=issue MAX_ATTEMPTS=3
```

**How it works:**
1. **Attempt 1:** Run test with `--conversation --fail-fast --checkpoint-file`
2. **On failure:** Save checkpoint, extract failing prompt index, run fix agent
3. **Attempt 2+:** Fork from checkpoint before failing prompt, run only that prompt
4. **Fix agent session:** Maintains single Claude session across attempts (sees all previous fixes)

**Flow:**
```
Attempt 1: Run all prompts → Fail at prompt N → Checkpoint at N-1 → Fix agent edits
Attempt 2: Fork from N-1 → Run prompt N → Still fails → Fix agent continues with history
Attempt 3: Fork from N-1 → Pass → Success! OR Fail at M → New checkpoint at M-1
```

**Benefits:**
- Skip replaying passed prompts (uses fork from checkpoint)
- Fix agent sees full conversation history (what was tried, what failed)
- Cumulative context helps agent avoid repeating failed fixes

## Mock Mode Debugging

Quick verification workflow when mock tests fail.

**Required variables** (set before running commands):
```bash
export JIRA_SKILLS_PATH=/path/to/Jira-Assistant-Skills  # Root repo
export JIRA_PLUGIN_PATH=$JIRA_SKILLS_PATH/plugins/jira-assistant-skills
export JIRA_LIB_PATH=$JIRA_SKILLS_PATH/jira-assistant-skills-lib
export JIRA_DIST_PATH=$JIRA_SKILLS_PATH/dist
```

**Step 1: Verify mock mode activates**
```bash
docker run --rm -e JIRA_MOCK_MODE=true \
    -v $JIRA_LIB_PATH:/opt/jira-lib:ro \
    --entrypoint bash jira-demo-container:latest \
    -c "pip install -q -e /opt/jira-lib && python3 -c '
from jira_assistant_skills_lib import get_jira_client
from jira_assistant_skills_lib.mock import is_mock_mode
print(f\"is_mock_mode(): {is_mock_mode()}\")
print(f\"Client type: {type(get_jira_client()).__name__}\")
'"
# Expected: is_mock_mode(): True, Client type: MockJiraClient
```

**Step 1b: Verify jira-as CLI is available**
```bash
docker run --rm \
    -v $JIRA_DIST_PATH:/opt/jira-dist:ro \
    --entrypoint bash jira-demo-container:latest \
    -c "pip install -q /opt/jira-dist/*.whl && which jira-as && jira-as --help | head -5"
# Expected: /home/devuser/venv/bin/jira-as, followed by help text
# If "jira-as not found": wheel may be missing or outdated - run `hatch build` in jira-assistant-skills repo
```

**Step 2: Test CLI commands directly**
```bash
docker run --rm -e JIRA_MOCK_MODE=true \
    -v $JIRA_LIB_PATH:/opt/jira-lib:ro \
    -v $JIRA_DIST_PATH:/opt/jira-dist:ro \
    --entrypoint bash jira-demo-container:latest \
    -c "pip install -q -e /opt/jira-lib /opt/jira-dist/*.whl && \
        jira-as search query 'project=DEMO'"
# Expected: Table of DEMO-84, DEMO-85, etc.
```

**Step 2b: Verify mock persistence works**
```bash
docker run --rm -e JIRA_MOCK_MODE=true \
    -e PYTHONPATH=/workspace/patches \
    -v $(pwd)/demo-container/patches:/workspace/patches:ro \
    -v $JIRA_LIB_PATH:/opt/jira-lib:ro \
    -v $JIRA_DIST_PATH:/opt/jira-dist:ro \
    --entrypoint bash jira-demo-container:latest \
    -c "pip install -q -e /opt/jira-lib /opt/jira-dist/*.whl && \
        jira-as issue create -p DEMO -t Bug -s 'Test' && \
        cat /tmp/mock_state.json && \
        jira-as issue get DEMO-101"
# Expected: Issue created, state file written, issue retrieved in second CLI call
```

**Step 3: Run full test only after scripts work**
```bash
make test-skill-mock-dev SCENARIO=issue PROMPT_INDEX=0 VERBOSE=1
```

**Common error patterns:**
| Error | Cause | Fix |
|-------|-------|-----|
| `ValidationError: JIRA URL not configured` | Mock not activating | Check `get_jira_client()` has `is_mock_mode()` check |
| `TypeError: got unexpected keyword argument` | Mock API incomplete | Add missing parameter to mock method |
| Tools: `['Skill', 'Bash']` | **CORRECT behavior** | This is expected! Skill loads context, Bash runs CLI |
| Tools: `['Skill', 'Bash', 'Bash', ...]` | Multiple CLI calls | May be correct if multiple operations needed |
| Tools: `['Skill', 'Bash', 'Skill', ...]` | Re-loading skill | Possible issue; skill should only load once per conversation |
| `jira-as: command not found` | CLI not installed | Install from wheel: `pip install /opt/jira-dist/*.whl` |
| Skill → setup → Bash exploration | CLI command failed | Check `which jira-as`; rebuild wheel with `hatch build` in `jira-assistant-skills-lib/` |
| "Tool accuracy: partial" with `['Skill', 'Bash']` | **FALSE NEGATIVE** | Test expectations wrong; `Skill → Bash` is correct |

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
