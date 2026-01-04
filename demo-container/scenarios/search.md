# JQL Search Scenario

This walkthrough demonstrates powerful search capabilities without memorizing JQL syntax.

## Step 1: Basic Search

```
Show me all open issues in DEMO
```

Claude translates this to JQL and returns matching issues.

## Step 2: Search by Type

```
Find all bugs in DEMO
```

```
Show me all stories in DEMO
```

## Step 3: Search by Priority

```
What are the high priority issues in DEMO?
```

## Step 4: Search by Status

```
Show me issues that are In Progress
```

```
Find issues that are not done in DEMO
```

## Step 5: Search by Assignee

```
What issues are assigned to me?
```

```
Show unassigned issues in DEMO
```

## Step 6: Combined Searches

```
Find high priority bugs that are still open in DEMO
```

```
Show me stories in DEMO that are in progress or to do
```

## Step 7: Time-based Searches

```
What issues were created this week in DEMO?
```

```
Show me issues updated in the last 24 hours
```

## Step 8: Text Search

```
Search for issues mentioning 'login' in DEMO
```

## Step 9: Save a Filter

```
Save this search as 'My Open Bugs': project = DEMO AND type = Bug AND status != Done
```

## Step 10: Run a Saved Filter

```
Run my saved filter 'My Open Bugs'
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
