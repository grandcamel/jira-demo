# Service Desk (JSM) Scenario

This walkthrough demonstrates Jira Service Management operations.

**Note:** The demo uses the DEMOSD service desk project with these request types:
- IT help
- Computer support
- New employee
- Travel request
- Purchase over $100 / under $100
- Employee exit

## Step 1: View Service Desk

```
Show me the DEMOSD service desk
```

This displays the service desk configuration and available request types.

## Step 2: View Request Types

```
What request types are available in DEMOSD?
```

You'll see IT help, Computer support, New employee, Travel request, and more.

## Step 3: View Open Requests

```
What are the open requests in DEMOSD?
```

You should see 5 seed requests:
- DEMOSD-1: VPN connection issue (IT help)
- DEMOSD-2: New laptop request (Computer support)
- DEMOSD-3: New hire onboarding (New employee)
- DEMOSD-4: Conference travel (Travel request)
- DEMOSD-5: Keyboard purchase (Purchase over $100)

## Step 4: View Request Details

```
Show me details of DEMOSD-1
```

DEMOSD-1 is a VPN connectivity issue submitted as an IT help request.

## Step 5: Create a New Request

```
Create an IT help request in DEMOSD: Printer not working on 3rd floor
```

## Step 6: Add Internal Comment

```
Add internal comment to DEMOSD-1: Checked VPN server logs - user's token expired
```

Internal comments are not visible to customers.

## Step 7: Add Customer Response

```
Reply to customer on DEMOSD-1: Please try disconnecting and reconnecting. If that fails, we'll reset your VPN credentials.
```

## Step 8: Check SLA Status

```
What's the SLA status for DEMOSD-1?
```

See time remaining before SLA breach.

## Step 9: View Queue

```
Show me the service desk queue for DEMOSD
```

## Step 10: Assign Request to Jane

```
Assign DEMOSD-1 to Jane Manager
```

Jane will handle this VPN connectivity issue.

## Step 11: Check Jane's Workload

```
What requests are assigned to Jane?
```

## Step 12: Resolve Request

```
Resolve DEMOSD-1 with resolution: VPN credentials reset, user reconnected successfully
```

## What You Learned

- Viewing service desk configuration and request types
- Managing customer requests
- Internal vs customer-visible comments
- SLA monitoring
- Queue management
- Request lifecycle

## Bonus: Advanced JSM

```
# View all SLA breaches
Show requests breaching SLA in DEMOSD

# View requests by type
Show me all IT help requests in DEMOSD

# Check new employee onboarding
What's the status of the new hire request DEMOSD-3?

# View travel requests
Find all travel requests in DEMOSD
```

## Next Steps

Try the bulk operations scenario: `cat /workspace/scenarios/bulk.md`
