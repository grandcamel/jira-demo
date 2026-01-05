---
description: Reset the local dev queue by restarting queue-manager
---

Reset the local dev queue by running:

```bash
docker-compose restart queue-manager
```

This will:
- Disconnect any active sessions
- Clear the in-memory queue
- Redis data (invites) will persist
