# JIRA Assistant Skills - Live Demo

One-click live demo for [JIRA Assistant Skills](https://github.com/grandcamel/jira-assistant-skills) with web-based terminal access.

## Features

- **Web Terminal**: Browser-based Claude Code terminal via ttyd
- **Queue System**: Single-user sessions with waitlist
- **Invite Access**: Token-based URLs for controlled demo access
- **Interactive Menu**: Choose scenarios, start Claude, or use bash shell
- **Pre-configured**: Claude auth (OAuth token or API key) + JIRA sandbox ready to use
- **Guided Scenarios**: Issue management, JQL search, Agile, JSM, observability (rendered with [glow](https://github.com/charmbracelet/glow))
- **Hands-free Mode**: Claude runs with `--permission-mode bypassPermissions` for seamless demos
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
    +-- demo-telemetry-network (external, shared with standalone containers)
```

## Quick Start (Local Development)

```bash
# Clone the repository
git clone https://github.com/grandcamel/jira-demo.git
cd jira-demo

# Copy example secrets
cp secrets/example.env secrets/.env

# Edit secrets/.env with your JIRA credentials

# Set Claude authentication (one of):
export CLAUDE_CODE_OAUTH_TOKEN="..."  # From 'claude setup-token'
# OR
export ANTHROPIC_API_KEY="..."        # API key

# On macOS, you can store the token in Keychain for auto-retrieval:
security add-generic-password -a "$USER" -s "CLAUDE_CODE_OAUTH_TOKEN" -w "<token>"

# Start services
make dev

# Open http://localhost:8080
```

## Deployment (DigitalOcean)

### Prerequisites

1. DigitalOcean account
2. Domain pointing to droplet IP
3. JIRA API token for jasonkrue.atlassian.net
4. Claude OAuth token (run `claude setup-token`) or API key

### Setup

```bash
# SSH to droplet
ssh root@your-droplet-ip

# Clone and setup
git clone https://github.com/grandcamel/jira-demo.git /opt/jira-demo
cd /opt/jira-demo

# Configure secrets
cp secrets/example.env secrets/.env
vim secrets/.env  # Add JIRA credentials + CLAUDE_CODE_OAUTH_TOKEN

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

### Claude Authentication

Set one of these environment variables (or add to `secrets/.env`):

```bash
# Option 1: OAuth token (Pro/Max subscription)
export CLAUDE_CODE_OAUTH_TOKEN="..."  # Run 'claude setup-token' to get this

# Option 2: API key
export ANTHROPIC_API_KEY="sk-ant-..."
```

**macOS Keychain** (recommended): Store the token for automatic retrieval:
```bash
security add-generic-password -a "$USER" -s "CLAUDE_CODE_OAUTH_TOKEN" -w "<token>"
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
make dev-down      # Stop local development
make build         # Build all containers
make deploy        # Deploy to production
make logs          # View logs
make reset-sandbox # Reset JIRA sandbox
make health        # Check production health
make health-local  # Check local dev health
make otel-logs     # View LGTM stack logs
make otel-reset    # Reset observability data

# Skill Testing
make test-skill-dev SCENARIO=search           # Test with assertions
make test-skill-dev SCENARIO=x CONVERSATION=1 # Multi-prompt context
make test-skill-dev SCENARIO=x FAIL_FAST=1    # Stop on first failure
make test-skill-mock-dev SCENARIO=search      # Test with mock API
make refine-skill SCENARIO=search             # Automated fix loop

# Invite Management
make invite                      # Generate invite (default 48h)
make invite EXPIRES=7d           # Generate with custom expiration
make invite-local                # Generate invite for local dev
make invite-list                 # List all invites
make invite-revoke TOKEN=abc123  # Revoke an invite

# Interactive Shell
make shell-demo                  # Interactive demo container
make shell-demo PROMPT="..."     # Run prompt non-interactively
make shell-demo MODEL=sonnet     # Override default model (opus)
```

### Testing Locally

```bash
# Start in development mode (no SSL)
make dev

# Generate an invite and open it
make invite-local
# Opens: http://localhost:8080/{TOKEN}
```

### Skill Testing & Refinement

Test JIRA skills with assertions and fast iteration:

```bash
# Run skill test with assertions
make test-skill-dev SCENARIO=search

# Multi-prompt conversation with fail-fast
make test-skill-dev SCENARIO=issue CONVERSATION=1 FAIL_FAST=1

# If prompt 7 fails, iterate on just that prompt (0-indexed)
make test-skill-dev SCENARIO=issue FORK_FROM=5 PROMPT_INDEX=6

# Test with mocked JIRA API (fast, no API calls)
make test-skill-mock-dev SCENARIO=search

# Automated refinement loop
make refine-skill SCENARIO=search
```

**Key features:**
- **Session checkpointing**: Saves state after each prompt for fast iteration
- **Fork from checkpoint**: Retry failed prompts without replaying earlier ones
- **Fail-fast mode**: Stop on first failure to save time and API costs
- **Mock API**: Test skill logic without hitting real JIRA API
- **LLM-as-judge**: Semantic quality evaluation beyond pattern matching

### Parallel Testing

Multiple skill tests can run simultaneously - all containers share the `demo-telemetry-network` for telemetry:

```bash
# Run all mock scenarios in parallel (recommended)
make test-all-mocks

# Run specific scenarios
make test-all-mocks SCENARIOS=search,issue,agile

# Manual parallel execution
make test-skill-dev SCENARIO=search &
make test-skill-dev SCENARIO=issue &
wait
```

## Observability

Integrated LGTM (Loki, Grafana, Tempo, Mimir/Prometheus) stack accessible during active demo sessions at `/grafana/`.

### Pre-built Dashboards

- **Skill Test Results**: parallel test telemetry, quality ratings, judge analysis, prompt/response logs
- **Queue Operations**: queue size, wait times, invite validation rates
- **Session Analytics**: session duration, TTYd spawn latency, cleanup times
- **Nginx Access Logs**: request logs, traffic analysis, error rates
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

| Project | Purpose |
|---------|---------|
| [as-demo](https://github.com/grandcamel/as-demo) | Unified platform (Confluence + JIRA + Splunk) |
| [JIRA Assistant Skills](https://github.com/grandcamel/jira-assistant-skills) | Claude Code plugin |
| [claude-devcontainer](https://github.com/grandcamel/claude-devcontainer) | Base container image |
| [confluence-demo](https://github.com/grandcamel/confluence-demo) | Similar demo for Confluence |
| [splunk-demo](https://github.com/grandcamel/splunk-demo) | Similar demo for Splunk |
