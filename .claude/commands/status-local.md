---
description: Check full local dev system status
---

Check local dev system status:

```bash
echo "=== Local Dev Status ===" && \
echo "Health:" && curl -sf http://localhost:8080/health && echo " OK" || echo " FAILED" && \
echo "Queue:" && curl -s http://localhost:8080/api/status | jq -c && \
echo "Containers:" && docker-compose ps --format 'table {{.Name}}\t{{.Status}}'
```
