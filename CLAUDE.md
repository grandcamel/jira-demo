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
- **Dashboard reload requires container restart**: After editing dashboard JSON in `observability/dashboards/`, run `docker restart jira-demo-lgtm` to reload. Grafana's provisioning reload API is not available in the LGTM image.
- **Loki stat panel queries**: Plain log queries with `count` reduction don't work for stat panels. Use metric queries: `sum by () (count_over_time({job="skill-test"} |= \`event\` [$__range]))`.
- **LogQL JSON field filtering**: Use backticks for string values: `| json | quality = \`high\``. Without backticks, Loki treats it as a label reference.
- **Stat panel query type**: Grafana executes Loki metric queries as range queries by default, evaluating at multiple timestamps with overlapping windows. This causes stat panels to show ~60-100x inflated counts. Fix: add `"queryType": "instant"` to stat panel targets in dashboard JSON. Validate with direct Loki query: `curl 'http://localhost:3100/loki/api/v1/query' --data-urlencode 'query=sum(count_over_time({job="skill-test"} |= \`test_complete\` [1h]))'`.
- **Skill routing failures**: Common test failure pattern: jira-assistant hub routes to `jira-assistant-setup` instead of specific skills (`jira-search`, `jira-issue`, `jira-fields`). Check skill descriptions and routing logic.
- **Plugin cache embeds library copies**: The container's Claude plugin cache (`~/.claude/plugins/cache/jira-assistant-skills/.../skills/shared/scripts/lib/`) contains its **own embedded copy** of `jira-assistant-skills-lib`. Changes to the standalone lib repo don't affect the plugin until: (1) lib PR merged, (2) plugin updated to use new lib, (3) plugin published to GitHub, (4) container rebuilt.
- **Library changes need plugin update**: Changes to `jira-assistant-skills-lib` source aren't picked up by `make build` alone. The plugin pulls from GitHub, which has its own bundled library. To test lib changes: mount patched files into container or update the plugin's embedded lib.
- **Mock mode requires get_jira_client() check**: The `is_mock_mode()` check must be in the `get_jira_client()` convenience function (config_manager.py), not just ConfigManager methods. Skills call the convenience function via `from jira_assistant_skills_lib import get_jira_client`. Check BOTH the standalone lib AND the plugin's embedded copy.
- **Verify library version in container**: To check which library the container actually uses: `docker run --entrypoint bash jira-demo-container:latest -c 'grep -A5 "def get_jira_client" ~/.claude/plugins/cache/jira-assistant-skills/*/skills/shared/scripts/lib/config_manager.py'`
- **Telemetry reveals tool call cascades**: Loki `prompt_complete` events include `tools_called` array (e.g., `["Skill", "Bash", "Skill", "Bash"]`). Use this to diagnose unexpected tool usage patterns like credential check cascades.
- **Compare interactive vs mock tests**: When mock tests fail but interactive tests pass with the same prompt, check if the container has the latest library code. Stale container = mock client not activating = credential validation fails = Bash diagnostic cascade.
- **Mock client API parity**: Mock client methods must match real `JiraClient` signatures exactly. Common miss: `search_issues()` needs `next_page_token` parameter. Error pattern: `TypeError: MockJiraClientBase.search_issues() got an unexpected keyword argument 'next_page_token'`. Fix in `mock/base.py`, not config_manager.
- **Test scripts directly first**: Before running full `make test-skill-mock-dev`, test the skill script directly to get clearer errors. See "Mock Mode Debugging" section below.
- **Mock activation vs mock errors**: Different failure patterns: (1) Mock not activating = credential validation errors + Bash cascade. (2) Mock activated but incomplete = `TypeError` on mock methods. Verify activation first with quick Python test.
- **jira CLI from wheel, not editable install**: The `jira` CLI is defined in root `pyproject.toml` of `jira-assistant-skills` repo. Editable installs (`pip install -e`) fail due to broken venv symlinks in skill directories. Solution: install from pre-built wheel via `pip install /opt/jira-dist/*.whl`. Makefile targets mount `dist/` directory for this.
- **Rebuild wheel after package changes**: Changes to `jira-assistant-skills` package (CLI, skills) require rebuilding the wheel (`hatch build` or `python -m build`) before container will see them. The wheel is NOT auto-rebuilt.
- **Skill cascade on failure**: When Claude calls a Skill and the subsequent Bash command fails (e.g., `jira` not found), it cascades: Skill → Bash (fails) → setup skill → more Bash exploration. Root cause is usually missing CLI or misconfigured environment, not skill logic. Note: `Skill → Bash` is the CORRECT pattern (see below); only failure cascades are problematic.
- **skill-test.py baked into container**: The `skill-test.py` is copied into the container image at build time. Changes to `demo-container/skill-test.py` require either `make build` OR mounting the local file. Makefile dev targets now mount it automatically: `-v $(PWD)/demo-container/skill-test.py:/workspace/skill-test.py:ro`.
- **Judge needs skill execution context**: The LLM judge evaluates tool usage. Without context about how Claude Code skills work (`Skill → Bash` pattern), it will incorrectly penalize Bash usage as "extra tools". The judge prompt in `skill-test.py` includes this context - don't remove it.
- **Conversation mode context reuse**: In `CONVERSATION=1` mode, Claude may answer from context instead of re-calling CLI when data is already available. Example: After listing issues, "What's the status of DEMO-84?" may be answered from context without Bash. This causes tool expectation failures even when responses are correct. Design prompts to require fresh data or accept context reuse as valid.
- **Scenario tool expectations pattern**: For conversation mode scenarios, first prompt should `must_call: [Skill]`, subsequent prompts should `must_call: [Bash]`. The scenarios directory is mounted in dev targets for iteration without rebuild.

## How Claude Code Skills Work

**Fundamental concept**: Claude Code skills are context-loading mechanisms, NOT direct executors.

**The correct pattern:**
1. **Skill tool** → Loads SKILL.md content into Claude's context (instructions, examples, available scripts)
2. **Bash tool** → Claude executes the CLI commands described in the skill (e.g., `jira search query "..."`)

**Key behaviors:**
- Skill tool is activated by YAML frontmatter matching in SKILL.md
- Once loaded, the skill context persists for the entire conversation
- Subsequent operations should use Bash directly WITHOUT re-invoking the Skill tool
- ALL Claude Code skills work this way: context-loading + Bash execution

**Expected tool sequences:**
| Scenario | Expected Tools | Notes |
|----------|---------------|-------|
| First JIRA query in conversation | `['Skill', 'Bash']` | Skill loads context, Bash runs `jira` CLI |
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
| Shell access | `make shell-queue` / `make shell-demo` |
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

**Step 1b: Verify jira CLI is available**
```bash
docker run --rm \
    -v $JIRA_DIST_PATH:/opt/jira-dist:ro \
    --entrypoint bash jira-demo-container:latest \
    -c "pip install -q /opt/jira-dist/*.whl && which jira && jira --help | head -5"
# Expected: /home/devuser/venv/bin/jira, followed by help text
# If "jira not found": wheel may be missing or outdated - run `hatch build` in jira-assistant-skills repo
```

**Step 2: Test skill script directly**
```bash
docker run --rm -e JIRA_MOCK_MODE=true \
    -v $JIRA_PLUGIN_PATH:/home/devuser/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/dev:ro \
    -v $JIRA_LIB_PATH:/opt/jira-lib:ro \
    --entrypoint bash jira-demo-container:latest \
    -c "pip install -q -e /opt/jira-lib && \
        rm -rf ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 && \
        ln -sf dev ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/2.2.7 && \
        cd ~/.claude/plugins/cache/jira-assistant-skills/jira-assistant-skills/dev/skills/jira-search/scripts && \
        python3 jql_search.py 'project=DEMO'"
# Expected: Table of DEMO-84, DEMO-85, etc.
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
| `jira: command not found` | CLI not installed | Install from wheel: `pip install /opt/jira-dist/*.whl` |
| Skill → setup → Bash exploration | CLI command failed | Check `which jira`; rebuild wheel if outdated |
| `FileNotFoundError: .../venv/bin/python` | Editable install fails | Use wheel install instead of `-e` for root package |
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
