---
description: Create a local dev invite for the demo
arguments:
  - name: options
    description: "Optional: EXPIRES=7d TOKEN=demo LABEL='Description'"
---

Create a local dev invite by running:

```bash
make invite $ARGUMENTS
```

## Examples

Basic invite (48h expiration):
```
make invite
```

Custom expiration:
```
make invite EXPIRES=7d
```

Vanity URL (e.g., /demo):
```
make invite TOKEN=demo LABEL='Main Demo'
```

All options:
```
make invite EXPIRES=24h TOKEN=workshop LABEL='Workshop Session'
```

## Options

| Option | Description | Example |
|--------|-------------|---------|
| EXPIRES | Token lifespan | `1h`, `24h`, `7d` |
| TOKEN | Custom vanity token | `demo`, `workshop` |
| LABEL | Description for tracking | `'Customer Demo'` |
