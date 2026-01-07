# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

Live demo system for [JIRA Assistant Skills](https://github.com/grandcamel/jira-assistant-skills) Claude Code plugin. Provides web-based terminal access via ttyd with a queue/waitlist system for single-user sessions against a JIRA sandbox.

## Quick Start

```bash
make dev                    # Start local environment (http://localhost:8080)
make dev-down               # Stop local environment
make invite-local           # Generate invite URL for testing
make run-scenario SCENARIO=issue  # Run autoplay scenario in debug mode
```

## Architecture

```
nginx (reverse proxy) --> queue-manager (Node.js) --> ttyd --> demo-container
                              |                         |
                           redis                    LGTM stack
```

**Request flow:** `/` landing page, `/terminal` WebSocket to ttyd, `/api/*` queue manager

**Key directories:**
- `queue-manager/` - Node.js server managing demo sessions
- `demo-container/` - Docker image with Claude + JIRA plugin
- `scripts/` - Python scripts for JIRA sandbox management
- `observability/` - LGTM stack configuration

## Git Workflow

**Branch policy:** Never push directly to `main`. Always create a PR branch.

```bash
git checkout -b feature/my-change
git push -u origin feature/my-change
gh pr create
```

**Merge strategy:** Rebase only (linear history enforced)

## Common Operations

| Task | Command |
|------|---------|
| Start local dev | `make dev` |
| Check health | `make health-local` |
| View logs | `make logs` |
| Create invite | `make invite-local` |
| Reset sandbox | `make reset-sandbox` |
| Run scenario | `make run-scenario SCENARIO=search` |
| Shell into queue | `make shell-queue` |

---

# Level 2: Reference Documentation

<details>
<summary><strong>Full Command Reference</strong></summary>

### Development
```bash
make dev              # Start local environment (http://localhost:8080)
make dev-down         # Stop development environment
make build            # Build all containers
```

### Production
```bash
make deploy           # Deploy to production
make restart          # Restart all services
make start            # Start production services
make stop             # Stop production services
```

### Monitoring
```bash
make logs             # View all container logs
make logs-queue       # View queue manager logs
make logs-nginx       # View nginx logs
make health           # Check system health
make health-local     # Check local health
make status-local     # Full local status
```

### Observability
```bash
make otel-logs        # View LGTM stack logs
make otel-reset       # Reset observability data
```

### JIRA Sandbox
```bash
make reset-sandbox    # Reset sandbox (delete user issues, reset seed issues)
make seed-sandbox     # Seed sandbox with demo data
```

### Invite Management
```bash
make invite EXPIRES=48h              # Generate invite (default 48h)
make invite EXPIRES=7d LABEL="Demo"  # With custom label
make invite TOKEN=demo               # Vanity URL (/demo)
make invite-list                     # List all invites
make invite-list STATUS=pending      # Filter by status
make invite-info TOKEN=abc123        # Show invite details
make invite-revoke TOKEN=abc123      # Revoke invite
```

### Testing & Debugging
```bash
make run-scenario SCENARIO=issue           # Run scenario (3s delay)
make run-scenario SCENARIO=search DELAY=5  # Custom delay
make shell-queue      # Shell into queue manager
make shell-demo       # Run demo container interactively
```

### Token Management
```bash
make check-token      # Check OAuth token expiration
make refresh-token    # Re-authenticate Claude OAuth
```

</details>

<details>
<summary><strong>Slash Commands</strong></summary>

| Command | Description |
|---------|-------------|
| `/status` | Production system status |
| `/status-local` | Local dev system status |
| `/health` | Production health check |
| `/health-local` | Local health check |
| `/start` / `/start-local` | Start services |
| `/stop` / `/stop-local` | Stop services |
| `/restart` / `/restart-local` | Restart services |
| `/queue-status` / `/queue-status-local` | Queue status |
| `/queue-reset` / `/queue-reset-local` | Reset queue |
| `/invite` / `/invite-local` | Create invite |
| `/logs-errors` / `/logs-errors-local` | View errors from Loki |
| `/traces-errors` / `/traces-errors-local` | View error traces from Tempo |
| `/refresh-token` / `/refresh-prod-token` | OAuth token refresh commands |

**Creating slash commands:** Prefer Makefile targets over inline bash:
```markdown
---
description: My command
---
```bash
make my-target
```
```

</details>

<details>
<summary><strong>Environment Variables</strong></summary>

Required in `secrets/.env`:
```bash
JIRA_API_TOKEN=...
JIRA_EMAIL=...
JIRA_SITE_URL=https://jasonkrue.atlassian.net
SESSION_TIMEOUT_MINUTES=60  # Optional, default 60
MAX_QUEUE_SIZE=10           # Optional, default 10
```

**Claude files** (both required):
- `secrets/.credentials.json` - OAuth tokens (copy from `~/.claude/.credentials.json`)
- `secrets/.claude.json` - Config/settings (copy from `~/.claude/.claude.json`)

**Debug environment variables:**
- `AUTOPLAY_DEBUG=true` - Enable debug logging
- `AUTOPLAY_SHOW_TOOLS=true` - Show tool use in autoplay
- `OTEL_ENDPOINT=http://host.docker.internal:3100` - Loki endpoint for debug logs
- `ENABLE_AUTOPLAY=true` - Enable autoplay menu option

</details>

<details>
<summary><strong>Telemetry Reference</strong></summary>

### Loki (Logs)

**Stream Labels:**
| Label | Values | Description |
|-------|--------|-------------|
| `job` | `autoplay`, `nginx`, `nginx-error` | Log source |
| `scenario` | `issue`, `search`, `agile`, `jsm`, etc. | Autoplay scenario |
| `source` | `autoplay.sh` | Script source |
| `service_name` | `autoplay`, `nginx` | Service identifier |
| `status` | HTTP status codes | Nginx response status |

**Autoplay Log Content:**
```
PROMPT: <user prompt text>
Claude exit code: <0|1>
Output length: <chars> chars
```

**Nginx Log Fields (JSON):**
| Field | Description |
|-------|-------------|
| `time` | Request timestamp |
| `remote_addr` | Client IP |
| `request_method` | HTTP method |
| `request_uri` | Request path |
| `status` | HTTP status code |
| `body_bytes_sent` | Response size |
| `request_time` | Request duration |
| `upstream_response_time` | Backend response time |
| `http_user_agent` | User agent |

**Query examples:**
```bash
# Autoplay logs
curl -s "http://localhost:3100/loki/api/v1/query_range?query={job=\"autoplay\"}&limit=50"

# Nginx errors
curl -s "http://localhost:3100/loki/api/v1/query_range?query={job=\"nginx\",status=~\"5..\"}"
```

### Prometheus (Metrics)

| Metric | Type | Description |
|--------|------|-------------|
| `demo_queue_size` | Gauge | Current queue length |
| `demo_sessions_active` | Gauge | Active session count (0/1) |
| `demo_sessions_started_total` | Counter | Total sessions started |
| `demo_sessions_ended_total` | Counter | Total sessions ended |
| `demo_invites_validated_total` | Counter | Invite validations by status |
| `demo_session_duration_seconds` | Histogram | Session duration |
| `demo_queue_wait_seconds` | Histogram | Queue wait time |
| `demo_ttyd_spawn_seconds` | Histogram | Container spawn latency |
| `demo_sandbox_cleanup_seconds` | Histogram | Cleanup duration |

### Tempo (Traces)

**Cleanup Script Spans:**
| Span | Attributes |
|------|------------|
| `cleanup.delete_user_issues` | `project.key`, `dry_run` |
| `cleanup.reset_seed_issues` | `dry_run` |
| `cleanup.delete_comments` | `project.key`, `dry_run` |
| `cleanup.delete_worklogs` | `project.key`, `dry_run` |

**Seed Script Spans:**
| Span | Attributes |
|------|------------|
| `seed.find_user_by_name` | `user.account_id` |
| `seed.create_demo_issues` | `project.key`, `dry_run` |
| `seed.get_service_desk_id` | - |
| `seed.get_request_types` | - |
| `seed.create_demo_requests` | `project.key`, `dry_run` |

</details>

<details>
<summary><strong>WebSocket Protocol</strong></summary>

**Client to server:**
```json
{ "type": "join_queue", "inviteToken": "token" }
{ "type": "leave_queue" }
{ "type": "heartbeat" }
```

**Server to client:**
```json
{ "type": "queue_position", "position": 1, "estimated_wait": "5 min", "queue_size": 3 }
{ "type": "session_starting", "terminal_url": "/terminal", "expires_at": "..." }
{ "type": "session_ended", "reason": "timeout|disconnected|container_exit" }
{ "type": "invite_invalid", "reason": "not_found|expired|used|revoked", "message": "..." }
```

</details>

<details>
<summary><strong>JIRA Sandbox Details</strong></summary>

**Projects:** DEMO (Scrum), DEMOSD (JSM Service Desk)

**Seed issue identification:** Issues with label `demo` are preserved during cleanup. User-created issues (without label) are deleted.

**JIRA Accounts:**
- **Jason Krueger** (jasonkrue@gmail.com) - Claude's API access
- **Jane Manager** - Test user for JIRA web UI

**Jane's issues:**
- DEMO-3 (Login bug) - assigned to Jane
- DEMO-4 (API documentation) - assigned to Jane
- DEMO-8 (Search pagination) - reported by Jane

**Invite statuses:** `pending`, `used`, `expired`, `revoked`

**Redis schema:** `invite:{token}` stores JSON with token, expiration, status, session history.

</details>

<details>
<summary><strong>Production Deployment</strong></summary>

**Domain:** `assistant-skills.dev`
**Droplet:** DigitalOcean `jira-demo` (143.110.131.254)

**SSH access:** `ssh root@assistant-skills.dev`

**Deploy workflow:**
```bash
ssh root@assistant-skills.dev "cd /opt/jira-demo && git pull origin main && \
  docker-compose build queue-manager && \
  docker build -t jira-demo-container:latest ./demo-container && \
  docker-compose down && docker-compose up -d"
```

**Secrets permissions:**
```bash
chmod 644 secrets/.credentials.json secrets/.claude.json
```

**DNS:** `doctl compute domain records list assistant-skills.dev`

**SSL:** Let's Encrypt via certbot, auto-renews via cron

**Email:** ImprovMX forwards `*@assistant-skills.dev` to admin

</details>

<details>
<summary><strong>Docker Compose Files</strong></summary>

- `docker-compose.yml` - Production (ports 80/443, SSL)
- `docker-compose.dev.yml` - Dev overrides (port 8080, no SSL, hot reload)

**Local dev:**
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

**LGTM ports (dev):**
- 3001 - Grafana
- 3100 - Loki push API
- 4317 - OTLP gRPC
- 4318 - OTLP HTTP

</details>

<details>
<summary><strong>Autoplay Scenarios</strong></summary>

**Available scenarios:** issue, search, agile, jsm, admin, bulk, collaborate, dev, fields, relationships, time, observability

**Running scenarios:**
```bash
make run-scenario SCENARIO=issue           # Auto-advance, 3s delay
make run-scenario SCENARIO=search DELAY=5  # Custom delay
```

**Scenario files:**
- `demo-container/scenarios/*.md` - Markdown guides
- `demo-container/scenarios/*.prompts` - Autoplay prompts

**Debug mode:** Set `AUTOPLAY_DEBUG=true` to enable:
- Debug log file: `/tmp/autoplay-debug.log`
- OTEL log shipping to Loki
- Claude `--debug` flag

</details>

<details>
<summary><strong>Claude Code Plugins</strong></summary>

### Installed Plugins

**best-practices** - Git workflow, slash commands, Docker, secrets guidance

### Adding Local Plugins

```
my-plugin-repo/
├── .claude-plugin/
│   └── marketplace.json
└── my-plugin/
    ├── plugin.json
    └── skills/
        └── SKILL.md
```

**marketplace.json:**
```json
{
  "name": "my-marketplace",
  "owner": { "name": "your-name" },
  "plugins": [{
    "name": "my-plugin",
    "source": "./my-plugin",
    "description": "..."
  }]
}
```

**plugin.json:**
```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "author": { "name": "your-name" },
  "skills": "./skills/"
}
```

**Install:**
```bash
claude plugin marketplace add /path/to/repo
claude plugin install my-plugin
```

**Gotchas:**
- `source` must start with `./`
- `author` must be object `{"name": "..."}`
- `skills` is a path string, not array
- Skill files need YAML frontmatter with `description`

</details>
