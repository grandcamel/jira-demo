---
description: View recent errors from production Loki logs
---

View recent errors from production:

```bash
ssh root@assistant-skills.dev "docker-compose -f /opt/jira-demo/docker-compose.yml logs --tail=100 2>&1 | grep -iE 'error|failed|exception'"
```

Or query Loki directly for the last hour:

```bash
ssh root@assistant-skills.dev 'curl -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode "query={job=~\".+\"} |~ \"(?i)error|failed|exception\"" \
  --data-urlencode "start=$(date -d \"1 hour ago\" +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000" \
  --data-urlencode "limit=50" | jq -r ".data.result[].values[][1]"'
```

Or view all recent queue-manager logs:

```bash
ssh root@assistant-skills.dev "cd /opt/jira-demo && docker-compose logs --tail=50 queue-manager"
```
