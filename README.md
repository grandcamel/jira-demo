# JIRA Assistant Skills - Live Demo

One-click live demo for [JIRA Assistant Skills](https://github.com/grandcamel/jira-assistant-skills) with web-based terminal access.

## Features

- **Web Terminal**: Browser-based Claude Code terminal via ttyd
- **Queue System**: Single-user sessions with waitlist
- **Pre-configured**: Claude OAuth + JIRA sandbox ready to use
- **Guided Scenarios**: Issue management, JQL search, Agile, JSM
- **Auto-cleanup**: JIRA sandbox resets between sessions

## Architecture

```
Internet --> nginx (SSL) --> DigitalOcean Droplet
    |
    +-- /           --> Landing Page
    +-- /terminal   --> ttyd WebSocket
    +-- /api        --> Queue Manager
    |
    Docker
    +-- demo-container (claude-devcontainer + jira-skills)
    +-- queue-manager (Node.js)
    +-- redis (queue state)
```

## Quick Start (Local Development)

```bash
# Clone the repository
git clone https://github.com/grandcamel/jira-demo.git
cd jira-demo

# Copy example secrets
cp secrets/example.env secrets/.env
cp secrets/example.claude.json secrets/.claude.json

# Edit secrets with your credentials
# - secrets/.env: JIRA credentials
# - secrets/.claude.json: Claude OAuth tokens

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

cp secrets/example.claude.json secrets/.claude.json
vim secrets/.claude.json  # Add Claude OAuth tokens

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

### Claude OAuth (secrets/.claude.json)

Run `claude login` on your local machine, then copy the credentials:

```bash
# On your local machine
cat ~/.claude/.credentials.json

# Copy the output to secrets/.claude.json on the server
```

## JIRA Sandbox

The demo uses a pre-configured JIRA sandbox at `jasonkrue.atlassian.net`:

### DEMO Project (Scrum)

| Key | Type | Summary | Status |
|-----|------|---------|--------|
| DEMO-1 | Epic | Product Launch | Open |
| DEMO-2 | Story | User Authentication | Open |
| DEMO-3 | Bug | Login fails on mobile | Open |
| DEMO-4 | Task | Update documentation | To Do |
| DEMO-5 | Story | Dashboard redesign | In Progress |

### DEMOSD Service Desk (JSM)

| Key | Type | Summary |
|-----|------|---------|
| DEMOSD-1 | Get IT Help | Password reset needed |
| DEMOSD-2 | Request Access | New laptop request |

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
├── scripts/                # Deployment & maintenance
├── secrets/                # Credentials (.gitignored)
└── docs/                   # Documentation
```

### Make Commands

```bash
make dev          # Start local development
make build        # Build all containers
make deploy       # Deploy to production
make logs         # View logs
make reset-sandbox # Reset JIRA sandbox
make health       # Check system health
```

### Testing Locally

```bash
# Start in development mode (no SSL)
make dev

# Test the landing page
open http://localhost:8080

# Test the terminal directly
open http://localhost:7681
```

## Monitoring

- **Uptime**: UptimeRobot monitoring https://demo.jira-skills.dev/health
- **Logs**: `make logs` or `docker-compose logs -f`
- **Metrics**: DigitalOcean Droplet Metrics dashboard

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
