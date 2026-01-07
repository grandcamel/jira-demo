# Time Tracking Scenario

This walkthrough demonstrates comprehensive time tracking - logging work, estimates, reports, and timesheets.

## Step 1: Log Time

```
Log 2 hours on DEMO-3
```

Basic time logging to track work.

## Step 2: Log Time with Comment

```
Log 1 hour 30 minutes on DEMO-3 with comment: Debugging authentication flow
```

Add context to your time entries.

## Step 3: Log Time for Yesterday

```
Log 2 hours on DEMO-3 for yesterday
```

Backdate time entries when needed.

## Step 4: View Worklogs

```
Show me all time logged on DEMO-3
```

See all work log entries for an issue.

## Step 5: View Time Tracking Summary

```
What is the time tracking status of DEMO-3?
```

See original estimate, remaining, and time spent.

## Step 6: Set Original Estimate

```
Set the original estimate for DEMO-4 to 2 days
```

## Step 7: Set Remaining Estimate

```
Set the remaining estimate for DEMO-4 to 1 day 4 hours
```

## Step 8: Log Without Adjusting Estimate

```
Log 30 minutes on DEMO-3 without adjusting the estimate
```

Keep estimate unchanged when logging time.

## Step 9: Generate My Time Report

```
Show me my time logged this week
```

Personal time tracking summary.

## Step 10: Project Time Report

```
Show time logged on project DEMO this month
```

Project-wide time summary.

## Step 11: Time Report Grouped by Day

```
Show my time this week grouped by day
```

Daily breakdown of logged time.

## Step 12: Time Report Grouped by User

```
Show time on DEMO this month grouped by user
```

Team time tracking summary.

## Step 13: Export Timesheet to CSV

```
Export time logged on DEMO last month to CSV
```

For billing and invoicing systems.

## Step 14: Preview Bulk Time Logging

```
Preview logging 15 minutes to DEMO-3, DEMO-4, and DEMO-5
```

Dry-run before bulk operations.

## Step 15: Delete a Worklog

```
Preview deleting the last worklog on DEMO-3
```

Always preview before deleting.

## What You Learned

- Logging time with comments and dates
- Viewing worklogs and time tracking summary
- Setting original and remaining estimates
- Controlling estimate adjustment behavior
- Generating time reports by period
- Grouping reports by day, user, or issue
- Exporting timesheets for billing
- Bulk time logging with dry-run preview

## Time Formats

| Format | Duration |
|--------|----------|
| `30m` | 30 minutes |
| `2h` | 2 hours |
| `1d` | 1 day (8 hours) |
| `1w` | 1 week (5 days) |
| `1d 4h 30m` | Combined |

## Estimate Adjustment Modes

| Mode | Effect |
|------|--------|
| `auto` | Reduce remaining by time logged |
| `leave` | No change to estimate |
| `new` | Set remaining to new value |
| `manual` | Reduce by specified amount |

## Report Periods

- `today`, `yesterday`
- `this-week`, `last-week`
- `this-month`, `last-month`
- Custom: `--since 2025-01-01 --until 2025-01-31`

## Next Steps

Return to the issue scenario: `cat /workspace/scenarios/issue.md`
