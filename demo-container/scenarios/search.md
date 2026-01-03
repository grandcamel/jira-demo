# JQL Search Scenario

This walkthrough demonstrates powerful search capabilities without memorizing JQL syntax.

## Step 1: Basic Search

```bash
claude "Show me all open issues in DEMO"
```

Claude translates this to JQL and returns matching issues.

## Step 2: Search by Type

```bash
claude "Find all bugs in DEMO"
```

```bash
claude "Show me all stories in DEMO"
```

## Step 3: Search by Priority

```bash
claude "What are the high priority issues in DEMO?"
```

## Step 4: Search by Status

```bash
claude "Show me issues that are In Progress"
```

```bash
claude "Find issues that are not done in DEMO"
```

## Step 5: Search by Assignee

```bash
claude "What issues are assigned to me?"
```

```bash
claude "Show unassigned issues in DEMO"
```

## Step 6: Combined Searches

```bash
claude "Find high priority bugs that are still open in DEMO"
```

```bash
claude "Show me stories in DEMO that are in progress or to do"
```

## Step 7: Time-based Searches

```bash
claude "What issues were created this week in DEMO?"
```

```bash
claude "Show me issues updated in the last 24 hours"
```

## Step 8: Text Search

```bash
claude "Search for issues mentioning 'login' in DEMO"
```

## Step 9: Save a Filter

```bash
claude "Save this search as 'My Open Bugs': project = DEMO AND type = Bug AND status != Done"
```

## Step 10: Run a Saved Filter

```bash
claude "Run my saved filter 'My Open Bugs'"
```

## What You Learned

- Natural language to JQL translation
- Searching by type, priority, status, assignee
- Combining multiple search criteria
- Time-based queries
- Text/keyword search
- Saving and running filters

## Next Steps

Try the agile scenario: `cat /workspace/scenarios/agile.md`
