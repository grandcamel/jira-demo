# Observability Scenario

This walkthrough demonstrates the integrated observability stack - explore metrics,
traces, and logs for this demo system using Grafana dashboards.

## Accessing Grafana

During your active session, Grafana is available at the `/grafana/` path on the
demo site. The dashboards are pre-configured with data sources for:

- **Prometheus** - Metrics from queue-manager and Redis
- **Tempo** - Distributed traces from demo operations
- **Loki** - Logs from nginx and application containers

## Pre-Built Dashboards

### Queue Operations Dashboard

View real-time queue metrics:
- Current queue size
- Sessions started/ended
- Invite validation rates
- Average wait times

### Session Analytics Dashboard

Track session performance:
- Session duration distribution
- TTYd spawn latency
- Sandbox cleanup times
- Active session status

### System Overview Dashboard

Monitor infrastructure health:
- Redis memory and operations
- Container resource usage
- Error rates by service

## Step 1: Generate Some Activity

Before exploring dashboards, generate activity that will produce telemetry data:

```
Show me all issues in DEMO project
```

```
What's the status of DEMO-1?
```

```
Create a task in DEMO: Test observability integration
```

This creates JIRA API calls that are traced through the system.

## Step 2: Explore Traces in Grafana

Open Grafana and navigate to **Explore** → **Tempo**:

1. Search for traces by service: `jira-demo-queue-manager`
2. Look for spans like:
   - `startSession` - Session initialization
   - `validateInvite` - Invite token validation
   - `runSandboxCleanup` - Post-session cleanup

Each trace shows the full request lifecycle with timing breakdowns.

## Step 3: View Metrics

Navigate to **Explore** → **Prometheus**:

Try these queries:
```
# Active sessions
jira_demo_sessions_active

# Queue size over time
jira_demo_queue_size

# Session duration histogram
histogram_quantile(0.95, jira_demo_session_duration_bucket)

# Invite validation count by status
sum by(status) (jira_demo_invites_validated_total)
```

## Step 4: Search Logs

Navigate to **Explore** → **Loki**:

Search for specific patterns:
```
{container="nginx"} |= "session"
{container="queue-manager"} |= "error"
{job="nginx"} | json | status >= 400
```

Nginx logs are in JSON format for easy parsing.

## Step 5: Correlate Across Signals

The power of observability is correlating data:

1. Find a slow request in traces
2. Check if related metrics show anomalies
3. Search logs for errors during that time

Use Grafana's **time range sync** to keep all panels aligned.

## What You Learned

- Navigating Grafana's Explore interface
- Understanding the three pillars: metrics, traces, logs
- Writing Prometheus PromQL queries
- Searching logs with Loki's LogQL
- Correlating signals for debugging

## Dashboard Locations

- Queue Operations: `/grafana/d/queue-ops`
- Session Analytics: `/grafana/d/sessions`
- System Overview: `/grafana/d/system`

## Next Steps

Try the collaboration scenario: `cat /workspace/scenarios/collaborate.md`
