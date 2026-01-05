---
description: View recent error traces from production Tempo
---

View recent error traces from Tempo:

```bash
ssh root@assistant-skills.dev 'curl -s "http://localhost:3200/api/search" \
  --data-urlencode "q={status=error}" \
  --data-urlencode "limit=20" | jq'
```

Search for traces with specific error tags:

```bash
ssh root@assistant-skills.dev 'curl -s "http://localhost:3200/api/search" \
  --data-urlencode "q={error=true}" \
  --data-urlencode "limit=20" | jq ".traces[] | {traceID, rootServiceName, startTimeUnixNano, durationMs}"'
```

Get a specific trace by ID:

```bash
ssh root@assistant-skills.dev 'curl -s "http://localhost:3200/api/traces/<TRACE_ID>" | jq'
```

Or view traces in Grafana (requires active session):

```
https://assistant-skills.dev/grafana/explore?orgId=1&left={"datasource":"tempo","queries":[{"refId":"A","queryType":"traceql","query":"{status=error}"}]}
```
