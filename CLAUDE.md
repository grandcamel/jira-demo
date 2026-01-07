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

- **Git workflow**: Never push to `main`. Always create PR branch, rebase merge only.
- **Secrets**: Never commit `secrets/`. Use env vars for JIRA credentials.
- **Seed issues**: Identified by `demo` label. User issues (no label) deleted on cleanup.
- **Slash commands**: Prefer Makefile targets over inline bash.

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

**Logs**: Query Loki with `{job="autoplay"}` or `{job="nginx"}`

**Traces**: Spans prefixed `cleanup.*` and `seed.*` in Tempo

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
