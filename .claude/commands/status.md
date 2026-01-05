---
description: Check full production system status
---

Check production system status:

```bash
echo "=== Production Status ==="; echo -n "Health: "; (curl -sf https://assistant-skills.dev/health > /dev/null && echo "OK" || echo "FAILED"); echo -n "Queue: "; curl -s https://assistant-skills.dev/api/status | jq -c; echo "Containers:"; ssh root@assistant-skills.dev "cd /opt/jira-demo && docker-compose ps --format 'table {{.Name}}\t{{.Status}}'"
```
