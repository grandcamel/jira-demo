# JIRA Assistant Skills - Live Demo

One-click live demo for [JIRA Assistant Skills](https://github.com/grandcamel/jira-assistant-skills) with web-based terminal access.

## Features

- **Web Terminal**: Browser-based Claude Code terminal via ttyd
- **Queue System**: Single-user sessions with waitlist
- **Invite Access**: Token-based URLs for controlled demo access
- **Interactive Menu**: Choose scenarios, start Claude, or use bash shell
- **Pre-configured**: Claude OAuth + JIRA sandbox ready to use
- **Guided Scenarios**: Issue management, JQL search, Agile, JSM, observability (rendered with [glow](https://github.com/charmbracelet/glow))
- **Hands-free Mode**: Claude runs with `--dangerously-skip-permissions` for seamless demos
- **Auto-cleanup**: JIRA sandbox resets between sessions
- **Full Observability**: Integrated Grafana dashboards with metrics, traces, and logs

## Architecture

```
Internet --> nginx (SSL) --> DigitalOcean Droplet
    |
    +-- /           --> Landing Page
    +-- /terminal   --> ttyd WebSocket
    +-- /api        --> Queue Manager
    +-- /grafana    --> Observability Dashboards
    |
    Docker
    +-- demo-container (claude-devcontainer + jira-skills)
    +-- queue-manager (Node.js + OpenTelemetry)
    +-- redis (queue state)
    +-- lgtm (Grafana, Prometheus, Tempo, Loki)
    +-- promtail (log shipping)
    +-- redis-exporter (Redis metrics)
```

## Quick Start (Local Development)

```bash
# Clone the repository
git clone https://github.com/grandcamel/jira-demo.git
cd jira-demo

# Copy example secrets
cp secrets/example.env secrets/.env
cp secrets/example.credentials.json secrets/.credentials.json
cp secrets/example.claude.json secrets/.claude.json

# Edit secrets with your credentials
# - secrets/.env: JIRA credentials
# - secrets/.credentials.json: Claude OAuth tokens (from ~/.claude/.credentials.json)
# - secrets/.claude.json: Claude config (from ~/.claude/.claude.json)

# Start services
make dev

# Open http://localhost:8080
```

## Deployment (DigitalOcean)

### Prerequisites

1. DigitalOcean account
2. Domain pointing to droplet IP
3. JIRA API token for jasonkrue.atlassian.net
4. Claude OAuth tokens (from `claude login`)

### Setup

```bash
# SSH to droplet
ssh root@your-droplet-ip

# Clone and setup
git clone https://github.com/grandcamel/jira-demo.git /opt/jira-demo
cd /opt/jira-demo

# Configure secrets
cp secrets/example.env secrets/.env
vim secrets/.env  # Add JIRA credentials

cp secrets/example.credentials.json secrets/.credentials.json
vim secrets/.credentials.json  # Add Claude OAuth tokens

cp secrets/example.claude.json secrets/.claude.json
vim secrets/.claude.json  # Add Claude config

# Deploy
make deploy
```

### SSL Setup (Let's Encrypt)

```bash
# Install certbot
apt-get install certbot python3-certbot-nginx

# Get certificate
certbot --nginx -d demo.jira-skills.dev

# Auto-renewal is configured automatically
```

## Configuration

### Environment Variables (secrets/.env)

```bash
# JIRA Configuration
JIRA_API_TOKEN=your-api-token
JIRA_EMAIL=your-email@example.com
JIRA_SITE_URL=https://jasonkrue.atlassian.net

# Session Configuration
SESSION_TIMEOUT_MINUTES=60
MAX_QUEUE_SIZE=10

# Domain (for production)
DOMAIN=demo.jira-skills.dev
```

### Claude Files

Run `claude login` on your local machine, then copy both files:

```bash
# On your local machine - copy both files to secrets/
cp ~/.claude/.credentials.json secrets/.credentials.json
cp ~/.claude/.claude.json secrets/.claude.json
```

## JIRA Sandbox

The demo uses a pre-configured JIRA sandbox at `jasonkrue.atlassian.net`:

### DEMO Project (Scrum)

Seed script creates 10 issues: 1 Epic, 3 Stories, 2 Bugs, 4 Tasks. Issues labeled `demo` are preserved during cleanup. Two issues are assigned to Jane Manager for search demos.

### DEMOSD Service Desk (JSM)

Seed script creates 5 service requests across various request types (IT help, Computer support, New employee, Travel, Purchase).

### Resetting the Sandbox

```bash
# After each demo session (automatic)
python scripts/cleanup_demo_sandbox.py

# Manual reset
make reset-sandbox
```

## Development

### Directory Structure

```
jira-demo/
├── docker-compose.yml      # Service orchestration
├── Makefile                # Common commands
├── nginx/                  # Reverse proxy config
├── landing-page/           # Static HTML/CSS/JS
├── queue-manager/          # Node.js WebSocket server
├── demo-container/         # Docker container config
├── observability/          # LGTM stack configuration
├── scripts/                # Deployment & maintenance
├── secrets/                # Credentials (.gitignored)
└── docs/                   # Documentation
```

### Make Commands

```bash
make dev           # Start local development
make build         # Build all containers
make deploy        # Deploy to production
make logs          # View logs
make reset-sandbox # Reset JIRA sandbox
make health        # Check system health
make otel-logs     # View LGTM stack logs
make otel-reset    # Reset observability data

# Invite Management
make invite                      # Generate invite (default 48h)
make invite EXPIRES=7d           # Generate with custom expiration
make invite-list                 # List all invites
make invite-revoke TOKEN=abc123  # Revoke an invite
```

### Testing Locally

```bash
# Start in development mode (no SSL)
make dev

# Generate an invite and open it
make invite
# Opens: http://localhost:8080/{TOKEN}
```

## Observability

Integrated LGTM (Loki, Grafana, Tempo, Mimir/Prometheus) stack accessible during active demo sessions at `/grafana/`.

### Pre-built Dashboards

- **Queue Operations**: queue size, wait times, invite validation rates
- **Session Analytics**: session duration, TTYd spawn latency, cleanup times
- **System Overview**: Redis metrics, container health, error rates

### Make Commands

```bash
make otel-logs   # View LGTM stack logs
make otel-reset  # Reset observability data (fresh start)
```

### Custom Metrics

| Metric | Description |
|--------|-------------|
| `jira_demo_queue_size` | Current queue length |
| `jira_demo_sessions_active` | Active session count |
| `jira_demo_sessions_started_total` | Total sessions started |
| `jira_demo_session_duration_seconds` | Session duration histogram |
| `jira_demo_invites_validated_total` | Invite validation by status |

## Monitoring

- **Uptime**: UptimeRobot monitoring https://demo.jira-skills.dev/health
- **Logs**: `make logs` or `docker-compose logs -f`
- **Metrics**: Grafana dashboards at `/grafana/` during sessions

## Cost

| Item | Monthly |
|------|---------|
| DigitalOcean Droplet (4GB) | $24 |
| Reserved IP | $4 |
| Domain | ~$1 |
| **Total** | **~$29** |

## License

MIT License - see [LICENSE](LICENSE) for details.

## Related Projects

- [JIRA Assistant Skills](https://github.com/grandcamel/jira-assistant-skills) - The Claude Code plugin
- [claude-devcontainer](https://github.com/grandcamel/claude-devcontainer) - Base container image
