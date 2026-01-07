# Bulk Operations Scenario

This walkthrough demonstrates bulk operations for managing multiple issues at once with safety features like dry-run preview.

## Step 1: Create Test Issues

First, let's create some issues to work with:

```
Create 3 low priority tasks in DEMO with summary prefix "Cleanup:"
```

Claude will create DEMO-12, DEMO-13, DEMO-14 (or similar keys).

## Step 2: Preview Bulk Transition (Dry Run)

```
Preview moving all issues with "Cleanup" in the summary to In Progress
```

Dry-run mode shows what would happen without making changes. This is essential for safe bulk operations.

## Step 3: Execute Bulk Transition

```
Move all issues containing "Cleanup" in DEMO to In Progress
```

## Step 4: Bulk Assignment

```
Assign all my open issues to Jane Manager
```

## Step 5: Preview Bulk Priority Change

```
Show me what would happen if I changed all low priority tasks in DEMO to medium
```

## Step 6: Execute Bulk Priority Change

```
Change all low priority tasks in DEMO to medium priority
```

## Step 7: Preview Bulk Delete (Critical Safety Step)

```
Preview deleting all issues in DEMO with "Cleanup" in the summary
```

**IMPORTANT**: Always preview before bulk delete! This shows:
- Exact issues that would be deleted
- Any subtasks that would also be deleted
- Total count requiring confirmation

## Step 8: Execute Bulk Delete

```
Delete all issues in DEMO with "Cleanup" in the summary
```

You'll be asked to confirm when deleting more than 10 issues.

## Step 9: Bulk Operations with JQL

```
Transition all issues matching "project = DEMO AND status = 'To Do' AND created < -7d" to In Progress
```

## Step 10: Bulk Label Addition

```
Add label "legacy" to all bugs in DEMO that are older than 30 days
```

## What You Learned

- Using dry-run/preview mode for safety
- Bulk transitions across multiple issues
- Bulk assignments and priority changes
- Safe bulk deletion with confirmation
- Using JQL for precise bulk targeting
- Adding labels in bulk

## Safety Best Practices

1. **Always preview first** - Use "preview" or "show what would happen" before destructive operations
2. **Start small** - Test with a few issues before large batches
3. **Use specific criteria** - Be precise with JQL to avoid unintended changes
4. **Check subtasks** - Bulk delete includes subtasks automatically

## Next Steps

Try the admin scenario: `cat /workspace/scenarios/admin.md`
