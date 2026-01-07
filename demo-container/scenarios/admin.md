# Admin & Permissions Scenario

This walkthrough demonstrates JIRA administration tasks including permission diagnostics, project role management, and user administration.

## Step 1: Check Your Permissions

```
What permissions do I have on project DEMO?
```

This shows all permissions you have on a project - useful for understanding what you can do.

## Step 2: Find Missing Permissions

```
What permissions am I missing on DEMO?
```

Quickly identify permissions you don't have - helpful when troubleshooting "403 Forbidden" errors.

## Step 3: Check Specific Permission

```
Do I have permission to delete issues in DEMO?
```

Check a specific permission before attempting an operation.

## Step 4: List Project Roles

```
Show me the project roles and members for DEMO
```

See all roles (Administrators, Developers, etc.) and who is in each one.

## Step 5: View Specific Role Members

```
Who are the Administrators in project DEMO?
```

Focus on a specific role to see its members.

## Step 6: Add User to Project Role

```
Add Jane Manager to the Developers role in DEMO
```

Grant project access by adding users to roles.

## Step 7: Preview Role Removal (Dry Run)

```
Preview removing Jane Manager from Developers role in DEMO
```

Safety check before removing access.

## Step 8: Remove User from Role

```
Remove Jane Manager from the Developers role in DEMO
```

## Step 9: Search for Users

```
Search for users with "admin" in their name
```

Find users to add to roles or assign issues.

## Step 10: List Groups

```
Show me all JIRA groups
```

View available groups for permission schemes.

## Step 11: View Group Members

```
Who is in the jira-software-users group?
```

## Step 12: List All Projects

```
List all JIRA projects
```

## Step 13: Get Project Configuration

```
Show me the configuration for project DEMO
```

See which schemes (permission, notification, workflow) are assigned.

## What You Learned

- Checking your own permissions on projects
- Diagnosing "403 Forbidden" errors by finding missing permissions
- Listing project roles and their members
- Adding and removing users from project roles
- Searching for users and viewing groups
- Understanding project configuration

## Common Permission Issues

| Error | Likely Cause | Solution |
|-------|--------------|----------|
| 403 Forbidden | Missing permission | Check permissions, ask admin to grant |
| Can't see project | Not in any project role | Ask to be added to a role |
| Can't transition | Missing "Transition Issues" | Check workflow permissions |
| Can't delete | Missing "Delete Issues" | Usually reserved for admins |

## Next Steps

Explore the observability scenario: `cat /workspace/scenarios/observability.md`
