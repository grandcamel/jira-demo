# Custom Fields Scenario

This walkthrough demonstrates custom field discovery and configuration for JIRA projects.

## Step 1: List All Custom Fields

```
Show me all custom fields in JIRA
```

Lists all custom fields configured in your JIRA instance.

## Step 2: Find Agile Fields

```
Show me all Agile-related fields
```

Find Story Points, Epic Link, Sprint, and Rank fields.

## Step 3: Search for Specific Field

```
Find fields containing "story" in the name
```

Search for fields by name pattern.

## Step 4: Check Project Fields

```
What fields are available for project DEMO?
```

See which fields can be used when creating issues.

## Step 5: Check Fields for Issue Type

```
What fields are available for Stories in DEMO?
```

Different issue types may have different fields.

## Step 6: Check Agile Field Availability

```
Check if Agile fields are configured for project DEMO
```

Verify Story Points, Epic Link, Sprint are available.

## Step 7: Detect Project Type

```
Is DEMO a team-managed or company-managed project?
```

Project type affects field configuration options.

## Step 8: Preview Agile Configuration

```
Preview configuring Agile fields for DEMO
```

Dry-run to see what would be configured.

## Step 9: Find Field ID

```
What is the field ID for Story Points?
```

Field IDs are needed for API operations and JQL.

## Step 10: List System Fields

```
Show me all fields including system fields
```

See both custom and built-in JIRA fields.

## What You Learned

- Listing custom fields in a JIRA instance
- Finding Agile-specific fields (Story Points, Sprint, etc.)
- Checking field availability for projects and issue types
- Detecting project type (team-managed vs company-managed)
- Finding field IDs for API and JQL usage
- Understanding the difference between custom and system fields

## Common Agile Fields

| Field | Purpose | Typical ID |
|-------|---------|------------|
| Story Points | Effort estimation | `customfield_10016` |
| Epic Link | Link stories to epics | `customfield_10014` |
| Sprint | Sprint assignment | `customfield_10020` |
| Rank | Backlog ordering | `customfield_10019` |

**Note**: Field IDs vary between JIRA instances. Always use discovery commands to find correct IDs.

## Project Types

| Type | API Support | Field Config |
|------|-------------|--------------|
| Company-managed | Full | Via screens and schemes |
| Team-managed | Limited | Via project settings UI |

## Next Steps

Try the relationships scenario: `cat /workspace/scenarios/relationships.md`
