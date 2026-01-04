# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Live demo system for [JIRA Assistant Skills](https://github.com/grandcamel/jira-assistant-skills) Claude Code plugin. Provides web-based terminal access via ttyd with a queue/waitlist system for single-user sessions against a JIRA sandbox.

## Common Commands

```bash
# Development
make dev              # Start local environment (http://localhost:8080)
make dev-down         # Stop development environment

# Building
make build            # Build all containers including demo-container

# Production
make deploy           # Deploy to production
make restart          # Restart all services

# Monitoring
make logs             # View all container logs
make logs-queue       # View queue manager logs
make health           # Check system health

# Observability (Grafana + LGTM stack)
make otel-logs        # View LGTM stack logs
make otel-reset       # Reset observability data (fresh start)

# JIRA Sandbox
make reset-sandbox    # Reset JIRA sandbox to initial state (deletes user-created issues)
make seed-sandbox     # Seed JIRA sandbox with demo data

# Invite Management
make invite EXPIRES=48h              # Generate invite URL (default 48h)
make invite EXPIRES=7d LABEL="Demo"  # Generate with label
make invite-list                     # List all invites
make invite-list STATUS=pending      # Filter by status
make invite-info TOKEN=abc123        # Show invite details
make invite-revoke TOKEN=abc123      # Revoke an invite

# Debugging
make shell-queue      # Shell into queue manager container
make shell-demo       # Run demo container interactively
```

## Architecture

```
nginx (reverse proxy) --> queue-manager (Node.js) --> ttyd --> demo-container
                              |
                           redis (queue state)
```

**Request flow:**
- `/` - Landing page (static HTML/CSS/JS in `landing-page/`)
- `/terminal` - ttyd WebSocket proxy to active demo session
- `/api/*` - Queue manager REST API and WebSocket (`/api/ws`)

**Key components:**

- **queue-manager/** - Node.js Express + WebSocket server managing single-user demo sessions. Spawns ttyd processes that run demo containers. Uses Redis for queue persistence.

- **demo-container/** - Docker image based on `grandcamel/claude-devcontainer:enhanced`. Pre-installs JIRA Assistant Skills plugin and guided scenario docs in `/workspace/scenarios/`. Presents an interactive startup menu:
  1. **View Scenarios** - Browse guided walkthroughs (issue, search, agile, JSM)
  2. **Start Claude** - Launches `claude --dangerously-skip-permissions` for hands-free demo
  3. **Start Bash Shell** - Drop to shell for manual exploration

- **scripts/** - Python scripts using `jira-assistant-skills-lib`:
  - `cleanup_demo_sandbox.py` - Deletes user-created issues (key > 10), resets seed issues to initial state
  - `seed_demo_data.py` - Seeds JIRA sandbox with demo issues

## Invite System

Invite-based access control for demo sessions:

1. Generate invite: `make invite EXPIRES=7d`
2. User opens `/{TOKEN}` (e.g., `http://localhost:8080/FgVGfThU2KOPsxkT`)
3. Server validates invite when joining queue
4. On session end, invite marked as "used" with session details

**Invite statuses:** `pending`, `used`, `expired`, `revoked`

**Redis schema:** `invite:{token}` stores JSON with token, expiration, status, and session history.

## WebSocket Protocol (queue-manager)

Client to server:
- `{ type: "join_queue", inviteToken?: "token" }` - Join the waitlist
- `{ type: "leave_queue" }` - Leave the waitlist
- `{ type: "heartbeat" }` - Keep connection alive

Server to client:
- `{ type: "queue_position", position, estimated_wait, queue_size }`
- `{ type: "session_starting", terminal_url, expires_at }`
- `{ type: "session_ended", reason }` - reason: "timeout" | "disconnected" | "container_exit"
- `{ type: "invite_invalid", reason, message }` - reason: "not_found" | "expired" | "used" | "revoked"

## Environment Variables

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

**Token management:**
```bash
make check-token    # Check if OAuth token is expired or expiring soon
make refresh-token  # Launch Claude in container to re-authenticate (writes to secrets/)
```

## Docker Compose Files

- `docker-compose.yml` - Production config (ports 80/443, SSL)
- `docker-compose.dev.yml` - Development overrides (port 8080, no SSL, hot reload)

Use together for dev: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up`

## JIRA Sandbox

Projects: DEMO (Scrum), DEMOSD (JSM Service Desk)

Seed issues DEMO-1 through DEMO-10 are preserved during cleanup. Issues with higher keys are deleted between sessions.

## Observability

Integrated LGTM (Loki, Grafana, Tempo, Mimir/Prometheus) stack for full observability:

```
queue-manager (OTLP) --> lgtm:4318 --> Grafana dashboards
nginx (JSON logs) --> promtail --> Loki
redis --> redis-exporter --> Prometheus
```

**Access:** `/grafana/` during active demo sessions (auth via session cookie)

**Components:**
- **Prometheus** - Metrics from queue-manager and Redis
- **Tempo** - Distributed traces from demo operations
- **Loki** - Logs from nginx and application containers
- **Grafana** - Unified dashboards

**Pre-built dashboards:**
- Queue Operations - queue size, wait times, invite validation
- Session Analytics - duration, spawn latency, cleanup times
- System Overview - Redis metrics, error rates

**Custom metrics:**
- `jira_demo_queue_size` - Current queue length
- `jira_demo_sessions_active` - Active session count
- `jira_demo_sessions_started_total` - Session start counter
- `jira_demo_session_duration_seconds` - Session duration histogram
- `jira_demo_invites_validated_total` - Invite validation by status

**Config files:** `observability/` directory contains all LGTM configuration.
