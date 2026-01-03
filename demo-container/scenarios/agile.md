# Agile & Sprint Management Scenario

This walkthrough demonstrates sprint planning and backlog management.

## Step 1: View the Backlog

```bash
claude "Show me the backlog for project DEMO"
```

This displays unassigned issues not in any sprint.

## Step 2: View Current Sprint

```bash
claude "What's in the current sprint for DEMO?"
```

You should see the "Demo Sprint" with its issues.

## Step 3: Check Sprint Progress

```bash
claude "What's the sprint progress for DEMO?"
```

Claude shows completed vs remaining work.

## Step 4: View Epics

```bash
claude "Show me all epics in DEMO"
```

DEMO-1 "Product Launch" is the main epic.

## Step 5: View Epic Progress

```bash
claude "What's the progress on epic DEMO-1?"
```

See linked stories and their status.

## Step 6: Add Issue to Sprint

```bash
claude "Add DEMO-4 to the current sprint"
```

## Step 7: Estimate Story Points

```bash
claude "Set story points on DEMO-2 to 5"
```

## Step 8: Create a Story Under Epic

```bash
claude "Create a story in DEMO: API Rate Limiting, linked to epic DEMO-1, with 3 story points"
```

## Step 9: Prioritize Backlog

```bash
claude "Move DEMO-5 to the top of the backlog"
```

## Step 10: Sprint Velocity

```bash
claude "What's the velocity for DEMO over the last 3 sprints?"
```

## What You Learned

- Viewing and managing backlogs
- Sprint progress tracking
- Epic management and linking
- Story point estimation
- Backlog prioritization
- Velocity analysis

## Next Steps

Try the service desk scenario: `cat /workspace/scenarios/jsm.md`
