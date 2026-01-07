# Developer Integration Scenario

This walkthrough demonstrates Git and developer workflow integration - branch names, PR descriptions, and commit linking.

## Step 1: Generate a Branch Name

```
Generate a git branch name for DEMO-3
```

Creates a standardized branch name from the issue key and summary.

## Step 2: Branch Name with Auto-Prefix

```
Generate a branch name for DEMO-3 with automatic prefix based on issue type
```

Bug issues get `bugfix/`, Stories get `feature/`, etc.

## Step 3: Branch Name with Custom Prefix

```
Generate a hotfix branch name for DEMO-3
```

## Step 4: Get Git Checkout Command

```
Give me the git checkout command for DEMO-3
```

Get a ready-to-use git command.

## Step 5: Parse Commits for Issue Keys

```
What JIRA issues are mentioned in this commit: "feat(DEMO-123): add login feature"
```

Extract issue keys from commit messages.

## Step 6: Generate PR Description

```
Generate a pull request description for DEMO-3
```

Creates a PR description from the issue details.

## Step 7: PR Description with Checklist

```
Generate a PR description for DEMO-3 with a testing checklist
```

Includes a testing checklist in the PR.

## Step 8: PR Description with Labels

```
Generate a PR description for DEMO-3 including labels and components
```

## Step 9: Link a Commit to an Issue

```
Link commit abc123 to DEMO-3 with message "fix: resolve login timeout"
```

Creates a link between a Git commit and JIRA issue.

## Step 10: Link a Pull Request

```
Link PR https://github.com/org/repo/pull/456 to DEMO-3
```

## Step 11: View Linked Commits

```
Show me the commits linked to DEMO-3
```

See the development panel information.

## Step 12: View Detailed Commits

```
Show detailed commit information for DEMO-3
```

## What You Learned

- Generating consistent Git branch names from issues
- Auto-detecting branch prefixes from issue types
- Extracting issue keys from commit messages
- Creating PR descriptions from issue details
- Linking commits and PRs to JIRA issues
- Viewing development panel information

## Branch Naming Conventions

| Issue Type | Prefix | Example |
|------------|--------|---------|
| Bug | `bugfix/` | `bugfix/DEMO-3-login-timeout` |
| Story | `feature/` | `feature/DEMO-5-user-profile` |
| Task | `feature/` | `feature/DEMO-7-add-logging` |
| Hotfix | `hotfix/` | `hotfix/DEMO-9-critical-fix` |

## Developer Workflow

1. **Start**: Generate branch name from issue
2. **Code**: Make commits referencing issue key
3. **PR**: Generate PR description from issue
4. **Link**: Connect PR to JIRA for traceability
5. **Merge**: Auto-transition issue (with automation)

## Next Steps

Try the custom fields scenario: `cat /workspace/scenarios/fields.md`
