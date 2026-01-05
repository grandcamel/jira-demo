---
description: Reset the production queue by restarting queue-manager
---

Reset the production queue by running:

```bash
ssh root@assistant-skills.dev "cd /opt/jira-demo && docker-compose restart queue-manager"
```

This will:
- Disconnect any active sessions
- Clear the in-memory queue
- Redis data (invites) will persist
