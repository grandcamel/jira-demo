# Collaboration Scenario

This walkthrough demonstrates team collaboration features - comments, attachments, watchers, and notifications.

## Step 1: Add a Comment

```
Add a comment to DEMO-3: Starting investigation of the login bug
```

Comments help track progress and communicate with the team.

## Step 2: Add a Rich Text Comment

```
Add a formatted comment to DEMO-3 with bold and code: **Root cause found** - the issue is in `auth.validateToken()`
```

Claude supports markdown formatting in comments.

## Step 3: List Comments

```
Show me all comments on DEMO-3
```

View the conversation history for an issue.

## Step 4: Add an Internal Comment

```
Add an internal comment to DEMO-3 visible only to Administrators: Security review needed before fix
```

Internal comments are restricted to specific roles.

## Step 5: List Watchers

```
Who is watching DEMO-3?
```

Watchers receive notifications about issue changes.

## Step 6: Add a Watcher

```
Add Jane Manager as a watcher on DEMO-3
```

## Step 7: Remove a Watcher

```
Remove Jane Manager from watching DEMO-3
```

## Step 8: Send a Notification

```
Send a notification to watchers of DEMO-3 with subject "Fix Ready" and message "The fix is ready for testing"
```

## Step 9: Preview Notification (Dry Run)

```
Preview sending a notification to the assignee and reporter of DEMO-3
```

Always preview before sending to verify recipients.

## Step 10: View Activity History

```
Show me the activity history for DEMO-3
```

See all changes made to an issue over time.

## Step 11: Filter Activity by Field

```
Show status and assignee changes for DEMO-3
```

Focus on specific field changes.

## Step 12: Upload an Attachment

```
Upload screenshot.png to DEMO-3
```

Note: This requires a file to exist. In practice, provide the file path.

## What You Learned

- Adding plain and formatted comments
- Using internal comments for restricted visibility
- Managing watchers for issue notifications
- Sending targeted notifications
- Viewing issue activity and change history
- Uploading and managing attachments

## Collaboration Patterns

| Scenario | Actions |
|----------|---------|
| Starting work | Add comment, add yourself as watcher |
| Blocked | Comment + notify assignee/reporter |
| Handoff | Comment + reassign + notify new owner |
| Escalation | Internal comment + notify team lead |
| Evidence | Upload screenshot/log + comment |

## Next Steps

Try the developer integration scenario: `cat /workspace/scenarios/dev.md`
