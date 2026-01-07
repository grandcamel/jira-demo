---
description: Check production system health
---

Check production health:

```bash
echo "Landing page:" && curl -sf https://jira-demo.assistant-skills.dev/health && echo " OK" || echo " FAILED"
echo "Queue manager:" && curl -sf https://jira-demo.assistant-skills.dev/api/status > /dev/null && echo " OK" || echo " FAILED"
echo "Queue status:" && curl -s https://jira-demo.assistant-skills.dev/api/status | jq -c
```
