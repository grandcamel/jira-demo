# Issue Management Scenario

This walkthrough demonstrates core JIRA issue operations using natural language.

## Step 1: View Existing Issues

```
Show me all issues in project DEMO
```

You should see a list of pre-seeded issues including bugs, tasks, and stories.

## Step 2: Get Issue Details

```
What's the status of DEMO-84?
```

DEMO-84 is an Epic called "Product Launch". Claude will show you its details,
including linked issues.

## Step 3: Create a New Bug

```
Create a high priority bug in DEMO: Search results are not sorted correctly
```

This creates a new issue. Note the issue key returned (e.g., DEMO-11).

## Step 4: Update the Bug

```
Add a description to DEMO-11: When searching for issues, results appear in random order instead of by relevance
```

Replace DEMO-11 with your actual issue key.

## Step 5: View Jane's Assigned Issues

```
What issues are assigned to Jane?
```

DEMO-86 (Login bug) and DEMO-87 (API documentation) are assigned to Jane Manager.

## Step 6: Assign the Bug to Jane

```
Assign DEMO-11 to Jane Manager
```

## Step 7: Add a Comment

```
Add comment to DEMO-11: Investigating - looks like a sorting algorithm issue
```

## Step 8: Transition the Issue

```
Move DEMO-11 to In Progress
```

## Step 9: Log Time

```
Log 30 minutes on DEMO-11 with description: Initial investigation
```

## Step 10: Close the Issue

```
Close DEMO-11 with resolution Fixed
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
