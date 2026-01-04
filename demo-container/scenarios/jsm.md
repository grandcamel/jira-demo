# Service Desk (JSM) Scenario

This walkthrough demonstrates Jira Service Management operations.

**Note:** The demo uses the DEMOSD service desk project.

## Step 1: View Service Desk

```
Show me the DEMOSD service desk
```

This displays the service desk configuration and request types.

## Step 2: View Open Requests

```
What are the open requests in DEMOSD?
```

You should see DEMOSD-1 and DEMOSD-2.

## Step 3: View Request Details

```
Show me details of DEMOSD-1
```

DEMOSD-1 is a password reset request.

## Step 4: Create a New Request

```
Create a request in DEMOSD: Need access to the marketing drive
```

## Step 5: Add Internal Comment

```
Add internal comment to DEMOSD-1: Verified user identity via phone
```

Internal comments are not visible to customers.

## Step 6: Add Customer Response

```
Reply to customer on DEMOSD-1: Your password has been reset. Please check your email.
```

## Step 7: Check SLA Status

```
What's the SLA status for DEMOSD-1?
```

See time remaining before SLA breach.

## Step 8: View Queue

```
Show me the service desk queue for DEMOSD
```

## Step 9: Assign Request

```
Assign DEMOSD-1 to me
```

## Step 10: Resolve Request

```
Resolve DEMOSD-1 with resolution: Password reset completed
```

## What You Learned

- Viewing service desk configuration
- Managing customer requests
- Internal vs customer-visible comments
- SLA monitoring
- Queue management
- Request lifecycle

## Bonus: Advanced JSM

```
# View all SLA breaches
Show requests breaching SLA in DEMOSD

# Add customer to request
Add customer john@example.com to DEMOSD-2

# View request types
What request types are available in DEMOSD?
```

## What's Next?

Explore freely! Try combining skills:

```
Create a bug linked to request DEMOSD-1 about the password reset issue
```

Or ask Claude anything about your JIRA instance:

```
What projects do I have access to?
Who's the most active contributor this week?
Show me a summary of all open work
```
