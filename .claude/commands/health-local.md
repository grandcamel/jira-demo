---
description: Check local dev system health
---

Check local dev health:

```bash
echo "Landing page:" && curl -sf http://localhost:8080/health && echo " OK" || echo " FAILED"
echo "Queue manager:" && curl -sf http://localhost:8080/api/status > /dev/null && echo " OK" || echo " FAILED"
echo "Queue status:" && curl -s http://localhost:8080/api/status | jq -c
```
