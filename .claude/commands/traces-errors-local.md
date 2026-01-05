---
description: View recent error traces from local dev Tempo
---

View recent error traces from local Tempo:

```bash
curl -s "http://localhost:3200/api/search" \
  --data-urlencode "q={status=error}" \
  --data-urlencode "limit=20" | jq
```

Search for traces with specific error tags:

```bash
curl -s "http://localhost:3200/api/search" \
  --data-urlencode "q={error=true}" \
  --data-urlencode "limit=20" | jq '.traces[] | {traceID, rootServiceName, startTimeUnixNano, durationMs}'
```

Get a specific trace by ID:

```bash
curl -s "http://localhost:3200/api/traces/<TRACE_ID>" | jq
```

Or view traces in Grafana:

```
http://localhost:8080/grafana/explore?orgId=1&left={"datasource":"tempo","queries":[{"refId":"A","queryType":"traceql","query":"{status=error}"}]}
```
