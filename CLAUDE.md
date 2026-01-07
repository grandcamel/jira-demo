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
  1. **View Scenarios** - Browse guided walkthroughs (issue, search, agile, JSM, observability)
  2. **Start Claude** - Launches `claude --dangerously-skip-permissions` for hands-free demo
  3. **Start Bash Shell** - Drop to shell for manual exploration
  4. **Auto-play Scenario** - (experimental, hidden by default) Watch automated demo

- **scripts/** - Python scripts using `jira-assistant-skills-lib`:
  - `cleanup_demo_sandbox.py` - Deletes user-created issues (key > 10), resets seed issues to initial state
  - `seed_demo_data.py` - Seeds JIRA sandbox with demo issues (assigns some to Jane Manager)

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

**JIRA Accounts:**
- **Jason Krueger** (jasonkrue@gmail.com) - Claude's API access account
- **Jane Manager** - Test user for viewing JIRA web UI from another perspective

**Jane Manager's issues:**
- DEMO-3 (Login bug) - assigned to Jane
- DEMO-4 (API documentation) - assigned to Jane
- DEMO-8 (Search pagination bug) - reported by Jane

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

## Production Deployment

**Domains:**
- `jira-demo.assistant-skills.dev` - JIRA demo application
- `assistant-skills.dev` - Hub landing page (placeholder)

**Droplet:** DigitalOcean `jira-demo` (143.110.131.254)

SSH access: `ssh root@assistant-skills.dev`

**Deploy workflow:**
```bash
ssh root@assistant-skills.dev "cd /opt/jira-demo && git pull origin main && \
  docker-compose build queue-manager && \
  docker build -t jira-demo-container:latest ./demo-container && \
  docker-compose down && docker-compose up -d"
```

**Secrets file permissions:** Files in `secrets/` must be readable by container user:
```bash
chmod 644 secrets/.credentials.json secrets/.claude.json
```

**DNS management:** Use `doctl` CLI for DigitalOcean DNS:
```bash
doctl compute domain records list assistant-skills.dev
```

**SSL certificates:** Managed by Let's Encrypt (certbot), auto-renews via cron.
- `/etc/letsencrypt/live/assistant-skills.dev/` - root domain
- `/etc/letsencrypt/live/jira-demo.assistant-skills.dev/` - demo subdomain

**Email forwarding:** ImprovMX configured for `*@assistant-skills.dev` → forwards to admin email. Used for creating demo Atlassian accounts.

## Git Workflow

**Branch policy:** Never push directly to `main`. Always create a PR branch.

```bash
git checkout -b feature/my-change
# make changes and commit
git push -u origin feature/my-change
# create PR via GitHub
```

**Merge strategy:** Rebase only (linear history enforced)

- Merge commits: disabled
- Squash merge: disabled
- Rebase merge: enabled
- Auto-delete branches after merge: enabled

Keep commits atomic and well-described. PRs will be rebased onto `main`.

## Slash Commands

Available slash commands in `.claude/commands/`:

| Command | Description |
|---------|-------------|
| `/status` | Check full production system status |
| `/status-local` | Check full local dev system status |
| `/health` | Check production health |
| `/health-local` | Check local dev health |
| `/start` | Start production services |
| `/start-local` | Start local dev services |
| `/stop` | Stop production services |
| `/stop-local` | Stop local dev services |
| `/restart` | Restart production services |
| `/restart-local` | Restart local dev services |
| `/queue-status` | Check production queue |
| `/queue-status-local` | Check local dev queue |
| `/queue-reset` | Reset production queue |
| `/queue-reset-local` | Reset local dev queue |
| `/invite` | Create production invite |
| `/invite-local` | Create local dev invite |
| `/refresh-prod-token` | Display command to refresh production OAuth token |
| `/refresh-token` | Display command to refresh local OAuth token |
| `/logs-errors` | View production errors from Loki |
| `/logs-errors-local` | View local dev errors |
| `/traces-errors` | View production error traces from Tempo |
| `/traces-errors-local` | View local dev error traces |

**Creating new slash commands:**

Prefer calling Makefile targets to avoid shell quoting issues:

```markdown
---
description: My command description
---
\`\`\`bash
make my-target
\`\`\`
```

For complex logic, add a Makefile target first, then create a simple slash command that calls it.

## Experimental Features

**Auto-play scenarios** (disabled by default):

Automated scenario playback using expect to drive Claude through predefined prompts.

- Enable: Set `ENABLE_AUTOPLAY=true` in `docker-compose.dev.yml` queue-manager environment
- Prompts: `demo-container/scenarios/*.prompts`
- Script: `demo-container/autoplay.sh`

Status: Buggy - prompt submission timing issues with Claude Code's TUI.

## Claude Code Plugins

### Installed Plugins

**best-practices** - Development best practices for git workflow, slash commands, Docker, and secrets management. Provides guidance on:
- Git workflow (PR branches, rebase merges, atomic commits)
- Slash command patterns (Makefile targets over inline bash)
- Docker Compose layering (separate prod/dev files)
- Secrets permissions (`chmod 644` for container access)

### Adding Local Plugins

Claude Code plugins must be installed via marketplaces. For local plugin development:

1. **Directory structure** (source paths are relative to repo root, not marketplace.json):
   ```
   my-plugin-repo/
   ├── .claude-plugin/
   │   └── marketplace.json
   └── my-plugin/
       ├── plugin.json
       └── skills/
           └── SKILL.md
   ```

2. **marketplace.json format:**
   ```json
   {
     "name": "my-plugin-marketplace",
     "owner": {
       "name": "your-name"
     },
     "plugins": [
       {
         "name": "my-plugin",
         "source": "./my-plugin",
         "description": "Plugin description"
       }
     ]
   }
   ```

3. **plugin.json format:**
   ```json
   {
     "name": "my-plugin",
     "version": "1.0.0",
     "author": {
       "name": "your-name"
     },
     "description": "Plugin description",
     "skills": "./skills/"
   }
   ```

4. **Skill files** need YAML frontmatter with description:
   ```markdown
   ---
   description: When to use this skill...
   ---

   # Skill Content
   ```

5. **Install the plugin:**
   ```bash
   claude plugin marketplace add /path/to/my-plugin-repo
   claude plugin install my-plugin
   ```

**Key gotchas:**
- `source` in marketplace.json is relative to repo root, must start with `./`
- `author` must be an object `{"name": "..."}`, not a string
- `skills` in plugin.json is a path string, not an array
- Skill files need YAML frontmatter with `description`
