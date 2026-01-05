---
description: Create a production invite for the demo
arguments:
  - name: options
    description: "Optional: EXPIRES=7d TOKEN=demo LABEL='Description'"
---

Create a production invite by running this SSH command:

```bash
ssh root@assistant-skills.dev "cd /opt/jira-demo && make invite $ARGUMENTS"
```

## Examples

Basic invite (48h expiration):
```
ssh root@assistant-skills.dev "cd /opt/jira-demo && make invite"
```

Custom expiration:
```
ssh root@assistant-skills.dev "cd /opt/jira-demo && make invite EXPIRES=7d"
```

Vanity URL (e.g., /demo):
```
ssh root@assistant-skills.dev "cd /opt/jira-demo && make invite TOKEN=demo LABEL='Main Demo'"
```

All options:
```
ssh root@assistant-skills.dev "cd /opt/jira-demo && make invite EXPIRES=24h TOKEN=workshop LABEL='Workshop Session'"
```

## Options

| Option | Description | Example |
|--------|-------------|---------|
| EXPIRES | Token lifespan | `1h`, `24h`, `7d` |
| TOKEN | Custom vanity token | `demo`, `workshop` |
| LABEL | Description for tracking | `'Customer Demo'` |
