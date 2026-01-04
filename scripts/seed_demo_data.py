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
import sys
from typing import Any

try:
    from jira_assistant_skills_lib import get_jira_client, print_error, print_success
    from jira_assistant_skills_lib.error_handler import JiraError
except ImportError:
    print("Error: jira-assistant-skills-lib not installed")
    print("Run: pip install jira-assistant-skills-lib")
    sys.exit(1)

from otel_setup import init_telemetry, traced, add_span_attribute


# =============================================================================
# Seed Data Configuration
# =============================================================================

DEMO_PROJECT = "DEMO"
DEMO_SERVICE_DESK = "DEMOSD"

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
    },
    {
        "summary": "Update API documentation",
        "description": "Documentation for v2 API endpoints needs to be updated with new authentication flow.",
        "issuetype": "Task",
        "priority": "Medium",
        "labels": ["demo", "docs"],
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
DEMOSD_REQUESTS = [
    {
        "summary": "Password reset needed",
        "description": "I forgot my password and can't log in. Please help!",
        "request_type": "Get IT Help",
    },
    {
        "summary": "New laptop request",
        "description": "My current laptop is 4 years old and running very slow. Requesting a new MacBook Pro for development work.",
        "request_type": "Request Access",
    },
]


@traced("seed.create_demo_issues")
def create_demo_issues(client: Any, dry_run: bool = False) -> list[str]:
    """Create seed issues in DEMO project."""
    created_keys = []
    add_span_attribute("project.key", DEMO_PROJECT)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Creating issues in {DEMO_PROJECT}...")

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


@traced("seed.create_demo_requests")
def create_demo_requests(client: Any, dry_run: bool = False) -> list[str]:
    """Create seed requests in DEMOSD service desk."""
    created_keys = []
    add_span_attribute("project.key", DEMO_SERVICE_DESK)
    add_span_attribute("dry_run", dry_run)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Creating requests in {DEMO_SERVICE_DESK}...")

    for request_data in DEMOSD_REQUESTS:
        summary = request_data["summary"]

        if dry_run:
            print(f"  Would create: {request_data['request_type']} - {summary}")
            continue

        try:
            # For JSM, we use the service desk API
            # Note: This requires the service desk to be set up with these request types
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
            print(f"  Created: {issue_key} - {summary}")

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
    parser.add_argument("--profile", default="demo", help="JIRA profile to use (default: demo)")
    args = parser.parse_args()

    # Initialize OpenTelemetry tracing
    init_telemetry("jira-demo-seed")

    try:
        client = get_jira_client(profile=args.profile)

        print("=" * 60)
        print("JIRA Demo Sandbox Seeding")
        print("=" * 60)

        # Create DEMO project issues
        demo_keys = create_demo_issues(client, args.dry_run)

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
