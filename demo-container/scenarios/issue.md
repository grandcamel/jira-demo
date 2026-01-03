# Issue Management Scenario

This walkthrough demonstrates core JIRA issue operations using natural language.

## Step 1: View Existing Issues

```bash
claude "Show me all issues in project DEMO"
```

You should see a list of pre-seeded issues including bugs, tasks, and stories.

## Step 2: Get Issue Details

```bash
claude "What's the status of DEMO-1?"
```

DEMO-1 is an Epic called "Product Launch". Claude will show you its details,
including linked issues.

## Step 3: Create a New Bug

```bash
claude "Create a high priority bug in DEMO: Search results are not sorted correctly"
```

This creates a new issue. Note the issue key returned (e.g., DEMO-11).

## Step 4: Update the Bug

```bash
claude "Add a description to DEMO-11: When searching for issues, results appear in random order instead of by relevance"
```

Replace DEMO-11 with your actual issue key.

## Step 5: Assign the Bug

```bash
claude "Assign DEMO-11 to me"
```

## Step 6: Add a Comment

```bash
claude "Add comment to DEMO-11: Investigating - looks like a sorting algorithm issue"
```

## Step 7: Transition the Issue

```bash
claude "Move DEMO-11 to In Progress"
```

## Step 8: Log Time

```bash
claude "Log 30 minutes on DEMO-11 with description: Initial investigation"
```

## Step 9: Close the Issue

```bash
claude "Close DEMO-11 with resolution Fixed"
```

## What You Learned

- Creating issues with priority and type
- Viewing issue details and status
- Updating descriptions and adding comments
- Assigning issues
- Transitioning through workflow states
- Logging work time
- Resolving and closing issues

## Next Steps

Try the search scenario: `cat /workspace/scenarios/search.md`
