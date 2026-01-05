---
description: Start all local dev services
---

Start all local dev services:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Or with build:

```bash
make dev
```
