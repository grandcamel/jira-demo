#!/usr/bin/env python3
"""
Seed JIRA sandbox with demo data.

Creates sample issues in DEMO project and DEMOSD service desk
for live demonstrations.

Usage:
    python seed_demo_data.py
    python seed_demo_data.py --dry-run
"""

import argparse
from typing import Any

from sandbox_common import (
    DEMO_PROJECT,
    DEMO_SERVICE_DESK,
    JiraError,
    add_span_attribute,
    dry_run_prefix,
    get_jira_client,
    init_telemetry,
    print_error,
    print_success,
    traced,
)


# =============================================================================
# Seed Data Configuration
# =============================================================================

# Test user for demo scenarios (display name used for lookups)
JANE_MANAGER_DISPLAY_NAME = "Jane Manager"

# Seed issues for DEMO project
DEMO_ISSUES = [
    {
        "summary": "Product Launch",
        "description": "Epic for Q1 product launch including all related stories and tasks.",
        "issuetype": "Epic",
        "priority": "High",
        "labels": ["demo", "epic", "q1"],
    },
    {
        "summary": "User Authentication",
        "description": "Implement secure user authentication with OAuth 2.0 support.",
        "issuetype": "Story",
        "priority": "High",
        "labels": ["demo", "auth"],
        "story_points": 8,
        "epic_key": "DEMO-1",
    },
    {
        "summary": "Login fails on mobile Safari",
        "description": "Users report login button not responsive on iOS Safari.\n\nSteps to reproduce:\n1. Open app in Safari on iPhone\n2. Enter credentials\n3. Tap Login button\n\nExpected: User logs in\nActual: Nothing happens",
        "issuetype": "Bug",
        "priority": "High",
        "labels": ["demo", "mobile", "safari"],
        "assign_to_jane": True,  # Assigned to Jane Manager
    },
    {
        "summary": "Update API documentation",
        "description": "Documentation for v2 API endpoints needs to be updated with new authentication flow.",
        "issuetype": "Task",
        "priority": "Medium",
        "labels": ["demo", "docs"],
        "assign_to_jane": True,  # Assigned to Jane Manager
    },
    {
        "summary": "Dashboard redesign",
        "description": "Redesign the main dashboard with new analytics widgets and improved UX.",
        "issuetype": "Story",
        "priority": "Medium",
        "labels": ["demo", "ux"],
        "story_points": 5,
        "epic_key": "DEMO-1",
    },
    {
        "summary": "Performance optimization",
        "description": "Improve page load time from 3s to under 1s.",
        "issuetype": "Task",
        "priority": "Medium",
        "labels": ["demo", "performance"],
    },
    {
        "summary": "Add dark mode support",
        "description": "Implement system-aware dark mode with manual toggle option.",
        "issuetype": "Story",
        "priority": "Low",
        "labels": ["demo", "ux", "accessibility"],
        "story_points": 3,
    },
    {
        "summary": "Search pagination bug",
        "description": "Search results show duplicate items on page 2.",
        "issuetype": "Bug",
        "priority": "Medium",
        "labels": ["demo", "search"],
        "reporter_is_jane": True,  # Reported by Jane Manager
    },
    {
        "summary": "Email notification settings",
        "description": "Allow users to configure email notification preferences.",
        "issuetype": "Story",
        "priority": "Low",
        "labels": ["demo", "notifications"],
        "story_points": 2,
    },
    {
        "summary": "Security audit preparation",
        "description": "Prepare documentation and access for annual security audit.",
        "issuetype": "Task",
        "priority": "High",
        "labels": ["demo", "security"],
    },
]

# Seed requests for DEMOSD service desk
# Request types available: Computer support, Employee exit, IT help, New employee,
#                          Purchase over $100, Purchase under $100, Travel request, Emailed request
DEMOSD_REQUESTS = [
    {
        "summary": "Can't connect to VPN",
        "description": "I'm working from home and can't connect to the corporate VPN. Getting 'connection timeout' error.",
        "request_type": "IT help",
    },
    {
        "summary": "New laptop for development",
        "description": "My current laptop is 4 years old and running very slow. Requesting a new MacBook Pro for development work.",
        "request_type": "Computer support",
    },
    {
        "summary": "New hire starting Monday - Alex Chen",
        "description": "Alex Chen is joining the Engineering team on Monday. Please set up:\n- Email account\n- Slack access\n- GitHub organization access\n- JIRA account",
        "request_type": "New employee",
    },
    {
        "summary": "Conference travel to AWS re:Invent",
        "description": "Requesting approval for travel to AWS re:Invent in Las Vegas.\n- Dates: Dec 2-6\n- Estimated cost: $2,500 (flight + hotel + registration)",
        "request_type": "Travel request",
    },
    {
        "summary": "Purchase ergonomic keyboard",
        "description": "Requesting an ergonomic keyboard (Kinesis Advantage 360) for RSI prevention. Cost: $449",
        "request_type": "Purchase over $100",
    },
]


@traced("seed.find_user_by_name")
def find_user_by_name(client: Any, display_name: str) -> str | None:
    """Find a user's account ID by display name."""
    try:
        # Search for users by display name
        users = client.search_users(display_name)
        for user in users:
            if user.get("displayName") == display_name:
                account_id = user.get("accountId")
                add_span_attribute("user.account_id", account_id)
                return account_id
        return None
    except Exception as e:
        print(f"  Warning: Could not find user '{display_name}': {e}")
        return None


@traced("seed.create_demo_issues")
def create_demo_issues(client: Any, dry_run: bool = False, jane_account_id: str | None = None) -> list[str]:
    """Create seed issues in DEMO project."""
    created_keys = []
    add_span_attribute("project.key", DEMO_PROJECT)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{dry_run_prefix(dry_run)}Creating issues in {DEMO_PROJECT}...")

    for i, issue_data in enumerate(DEMO_ISSUES, 1):
        summary = issue_data["summary"]

        if dry_run:
            print(f"  Would create: {issue_data['issuetype']} - {summary}")
            created_keys.append(f"DEMO-{i}")
            continue

        try:
            # Build issue fields
            fields = {
                "project": {"key": DEMO_PROJECT},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": issue_data.get("description", "")}],
                        }
                    ],
                },
                "issuetype": {"name": issue_data["issuetype"]},
                "priority": {"name": issue_data.get("priority", "Medium")},
            }

            if issue_data.get("labels"):
                fields["labels"] = issue_data["labels"]

            # Set assignee if specified and Jane's account ID is available
            if issue_data.get("assign_to_jane") and jane_account_id:
                fields["assignee"] = {"accountId": jane_account_id}

            # Note: reporter field often can't be set on creation (screen config)
            # Skipping reporter_is_jane for now

            # Create issue
            result = client.create_issue(fields)
            issue_key = result["key"]
            created_keys.append(issue_key)
            print(f"  Created: {issue_key} - {summary}")

            # Set story points if specified (custom field)
            if issue_data.get("story_points"):
                try:
                    client.update_issue(issue_key, {"customfield_10016": issue_data["story_points"]})
                except Exception:
                    pass  # Story points field may not exist

            # Link to epic if specified
            if issue_data.get("epic_key"):
                try:
                    # Epic link is typically customfield_10014
                    client.update_issue(issue_key, {"customfield_10014": issue_data["epic_key"]})
                except Exception:
                    pass  # Epic link field may vary

        except JiraError as e:
            print(f"  Error creating {summary}: {e}")

    return created_keys


@traced("seed.get_service_desk_id")
def get_service_desk_id(client: Any, project_key: str) -> str | None:
    """Get the service desk ID for a project."""
    try:
        sd = client.lookup_service_desk_by_project_key(project_key)
        if sd:
            return sd.get("id")
        return None
    except Exception as e:
        print(f"  Warning: Could not get service desk ID: {e}")
        return None


@traced("seed.get_request_types")
def get_request_types(client: Any, service_desk_id: str) -> dict[str, int]:
    """Get request types for a service desk, returning name -> ID mapping."""
    try:
        response = client.get_request_types(service_desk_id)
        return {rt.get("name"): rt.get("id") for rt in response.get("values", [])}
    except Exception as e:
        print(f"  Warning: Could not get request types: {e}")
        return {}


@traced("seed.create_demo_requests")
def create_demo_requests(client: Any, dry_run: bool = False) -> list[str]:
    """Create seed requests in DEMOSD service desk using JSM API."""
    created_keys = []
    add_span_attribute("project.key", DEMO_SERVICE_DESK)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{dry_run_prefix(dry_run)}Creating requests in {DEMO_SERVICE_DESK}...")

    # Get service desk ID
    service_desk_id = None
    request_types = {}

    if not dry_run:
        print("  Looking up service desk...")
        service_desk_id = get_service_desk_id(client, DEMO_SERVICE_DESK)
        if service_desk_id:
            print(f"  Found service desk ID: {service_desk_id}")
            request_types = get_request_types(client, service_desk_id)
            if request_types:
                print(f"  Available request types: {', '.join(request_types.keys())}")
            else:
                print("  Warning: No request types found - using fallback issue creation")
        else:
            print(f"  Warning: Service desk not found for {DEMO_SERVICE_DESK} - using fallback")

    for request_data in DEMOSD_REQUESTS:
        summary = request_data["summary"]
        request_type_name = request_data.get("request_type", "Get IT Help")

        if dry_run:
            print(f"  Would create: {request_type_name} - {summary}")
            continue

        # Try JSM API first if we have service desk info
        if service_desk_id and request_type_name in request_types:
            try:
                request_type_id = str(request_types[request_type_name])
                result = client.create_request(
                    service_desk_id=service_desk_id,
                    request_type_id=request_type_id,
                    summary=summary,
                    description=request_data.get("description", ""),
                )
                issue_key = result.get("issueKey")
                created_keys.append(issue_key)
                print(f"  Created: {issue_key} - {summary} (via JSM API, type: {request_type_name})")
                continue
            except Exception as e:
                print(f"  JSM API failed for {summary}: {e}")
                print("  Falling back to standard issue creation...")

        # Fallback to standard issue creation
        try:
            fields = {
                "project": {"key": DEMO_SERVICE_DESK},
                "summary": summary,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": request_data.get("description", "")}],
                        }
                    ],
                },
                "issuetype": {"name": "Service Request"},
            }

            result = client.create_issue(fields)
            issue_key = result["key"]
            created_keys.append(issue_key)
            print(f"  Created: {issue_key} - {summary} (via standard API)")

        except JiraError as e:
            print(f"  Error creating {summary}: {e}")

    return created_keys


def main():
    parser = argparse.ArgumentParser(
        description="Seed JIRA sandbox with demo data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python seed_demo_data.py
    python seed_demo_data.py --dry-run
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without making changes")
    args = parser.parse_args()

    # Initialize OpenTelemetry tracing
    init_telemetry("jira-demo-seed")

    try:
        client = get_jira_client()

        print("=" * 60)
        print("JIRA Demo Sandbox Seeding")
        print("=" * 60)

        # Look up Jane Manager's account ID for assignee/reporter fields
        jane_account_id = None
        if not args.dry_run:
            print(f"\nLooking up test user '{JANE_MANAGER_DISPLAY_NAME}'...")
            jane_account_id = find_user_by_name(client, JANE_MANAGER_DISPLAY_NAME)
            if jane_account_id:
                print(f"  Found: {JANE_MANAGER_DISPLAY_NAME}")
            else:
                print(f"  Warning: '{JANE_MANAGER_DISPLAY_NAME}' not found - issues won't have assignee/reporter")

        # Create DEMO project issues
        demo_keys = create_demo_issues(client, args.dry_run, jane_account_id)

        # Create DEMOSD service desk requests
        sd_keys = create_demo_requests(client, args.dry_run)

        print("\n" + "=" * 60)
        if args.dry_run:
            print("[DRY RUN] Would create:")
        else:
            print("Created:")
        print(f"  {len(demo_keys)} issues in {DEMO_PROJECT}")
        print(f"  {len(sd_keys)} requests in {DEMO_SERVICE_DESK}")
        print("=" * 60)

        if not args.dry_run:
            print_success("Sandbox seeding complete!")

    except JiraError as e:
        print_error(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
