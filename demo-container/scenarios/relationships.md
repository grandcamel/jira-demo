# Issue Relationships Scenario

This walkthrough demonstrates issue linking, dependency management, and relationship analysis.

## Step 1: View Link Types

```
What link types are available in JIRA?
```

See all configured link types (Blocks, Duplicates, Relates to, etc.).

## Step 2: View Issue Links

```
Show me all links for DEMO-84
```

DEMO-84 (Product Launch Epic) has linked stories and tasks.

## Step 3: Create a Blocks Link

```
Link DEMO-86 blocks DEMO-87
```

DEMO-86 (Login bug) must be fixed before DEMO-87 (API documentation).

## Step 4: Create a Relates Link

```
Link DEMO-88 relates to DEMO-89
```

Create a general association between issues.

## Step 5: Create a Duplicate Link

```
Mark DEMO-91 as a duplicate of DEMO-86
```

Mark redundant issues for cleanup.

## Step 6: View Outward Links Only

```
Show me issues that DEMO-86 blocks
```

Filter links by direction.

## Step 7: Find Blockers

```
What is blocking DEMO-87?
```

See direct blockers for an issue.

## Step 8: Find Blocker Chain

```
Show me the full blocker chain for DEMO-87
```

Recursive analysis finds all transitive blockers.

## Step 9: Clone an Issue

```
Clone DEMO-86 to a new issue
```

Create a copy with a link to the original.

## Step 10: Clone with Subtasks

```
Clone DEMO-84 including subtasks and links
```

## Step 11: Remove a Link

```
Remove the blocks link between DEMO-86 and DEMO-87
```

## Step 12: Preview Link Removal

```
Preview removing all links from DEMO-91
```

Dry-run before removing links.

## Step 13: Get Link Statistics

```
Show link statistics for project DEMO
```

Analyze link patterns across the project.

## Step 14: Generate Dependency Graph

```
Generate a Mermaid diagram of dependencies for DEMO-84
```

Create visual documentation of relationships.

## What You Learned

- Viewing available link types
- Creating blocks, relates, and duplicate links
- Finding blockers and blocker chains
- Cloning issues with their relationships
- Removing links safely with preview
- Analyzing link statistics
- Generating dependency diagrams

## Link Types

| Type | Outward | Inward | When to Use |
|------|---------|--------|-------------|
| Blocks | blocks | is blocked by | Sequential dependencies |
| Duplicate | duplicates | is duplicated by | Mark redundant issues |
| Relates | relates to | relates to | General association |
| Clones | clones | is cloned by | Issue templates |

## Dependency Analysis

- **Direct blockers**: Issues immediately blocking this one
- **Blocker chain**: All transitive blockers (recursive)
- **Circular detection**: Automatic detection of dependency loops

## Next Steps

Try the time tracking scenario: `cat /workspace/scenarios/time.md`
